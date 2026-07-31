#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vitis_optima.py — Pilotage manuel des deux vérins (PCB v1, Raspberry Pi 5).

Trois boutons à action directe et indépendante :

    POSITION  abaisse le vérin de mise en position (distributeur 5/2 bistable,
              bobine maintenue alimentée)
    COUPE     impulsion sur le vérin de coupe (distributeur monostable) pendant
              TEMPS_DECOUPE, puis retour automatique par ressort
    RESET     coupe le vérin de coupe et remonte le vérin de mise en position

Tout passe par le MCP23017 en 0x24 : port A = relais, port B = boutons.
Aucun GPIO direct de la Raspberry Pi n'est utilisé.
L'arrêt d'urgence est câblé en dur et n'est pas vu par ce programme.

Deux propriétés garanties par construction :
  - les deux bobines du bistable ne sont jamais alimentées simultanément,
    car l'octet du port A est calculé à partir d'une seule variable d'état ;
  - à l'arrêt du programme (Ctrl+C, systemctl stop, erreur), toutes les
    sorties sont remises à zéro. Le vérin de coupe retombe par ressort ;
    le vérin de position, mécaniquement verrouillé par le bistable, reste
    où il est.

Lancement :   python3 vitis_optima.py
Arrêt :       Ctrl+C
"""

import signal
import sys
import time

import config as cfg
from mcp23017 import MCP23017


# Positionné par les gestionnaires de signaux, lu par la boucle principale.
_arret_demande = False


# ═══════════════════════════════════════════════════════════════════════
#  JOURNALISATION
# ═══════════════════════════════════════════════════════════════════════

def journal(message):
    """Affiche un message horodaté.

    flush=True est indispensable : sous systemd la sortie est un tube, donc
    bufferisée par blocs, et les messages n'apparaîtraient dans journalctl
    qu'avec plusieurs minutes de retard.
    """
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


# ═══════════════════════════════════════════════════════════════════════
#  VÉRIFICATION DE LA CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

def verifier_config():
    """Détecte les erreurs de saisie dans config.py avant tout mouvement.

    Le cas le plus dangereux est deux sorties sur le même bit : les deux
    bobines du bistable seraient alors alimentées ensemble.
    """
    sorties = {
        "BIT_EV_COUPE":     cfg.BIT_EV_COUPE,
        "BIT_POS_DESCENTE": cfg.BIT_POS_DESCENTE,
        "BIT_POS_MONTEE":   cfg.BIT_POS_MONTEE,
    }
    entrees = {
        "BIT_BTN_POSITION": cfg.BIT_BTN_POSITION,
        "BIT_BTN_COUPE":    cfg.BIT_BTN_COUPE,
        "BIT_BTN_RESET":    cfg.BIT_BTN_RESET,
    }

    for libelle, bits in (("sorties", sorties), ("entrées", entrees)):
        for nom, bit in bits.items():
            if not 0 <= bit <= 7:
                raise ValueError(f"config.py : {nom} = {bit} — doit être entre 0 et 7")
        if len(set(bits.values())) != len(bits):
            raise ValueError(
                f"config.py : deux {libelle} partagent le même bit — "
                + ", ".join(f"{n}={b}" for n, b in bits.items())
            )

    if cfg.TEMPS_DECOUPE <= 0:
        raise ValueError("config.py : TEMPS_DECOUPE doit être strictement positif")


def afficher_config():
    journal("Configuration active :")
    journal(f"    I2C bus {cfg.I2C_BUS_ID}, MCP23017 en 0x{cfg.MCP_ADDR:02X}")
    journal(f"    sortie GPA{cfg.BIT_EV_COUPE} → vérin de coupe (monostable)")
    journal(f"    sortie GPA{cfg.BIT_POS_DESCENTE} → position DESCENTE (bobine bistable)")
    journal(f"    sortie GPA{cfg.BIT_POS_MONTEE} → position MONTÉE   (bobine bistable)")
    journal(f"    entrée GPB{cfg.BIT_BTN_POSITION} → bouton POSITION")
    journal(f"    entrée GPB{cfg.BIT_BTN_COUPE} → bouton COUPE")
    journal(f"    entrée GPB{cfg.BIT_BTN_RESET} → bouton RESET")
    journal(f"    durée de coupe : {cfg.TEMPS_DECOUPE:.1f} s")
    if cfg.EXIGER_POSITION_AVANT_COUPE:
        journal("    garde-fou : coupe refusée si le vérin de position n'est pas en bas")


# ═══════════════════════════════════════════════════════════════════════
#  LECTURE DES BOUTONS
# ═══════════════════════════════════════════════════════════════════════

class Boutons:
    """Lecture des trois boutons avec anti-rebond et détection de front.

    Un seul accès I2C par tour de boucle : le port B est lu en une fois et
    les trois états en sont extraits.

    Anti-rebond par temps de stabilité : un changement n'est retenu que s'il
    se maintient pendant ANTI_REBOND. C'est plus fiable que la double lecture
    espacée d'un sleep, et cela ne bloque pas la boucle.
    """

    NOMS = ("position", "coupe", "reset")

    def __init__(self, mcp):
        self.mcp = mcp
        self._bits = {
            "position": cfg.BIT_BTN_POSITION,
            "coupe":    cfg.BIT_BTN_COUPE,
            "reset":    cfg.BIT_BTN_RESET,
        }
        self._stable = {nom: False for nom in self.NOMS}
        self._precedent = {nom: False for nom in self.NOMS}
        self._brut = {nom: False for nom in self.NOMS}
        self._depuis = {nom: time.monotonic() for nom in self.NOMS}

    def rafraichir(self):
        """Lit le port B et met à jour les états stabilisés."""
        octet = self.mcp.lire_entrees()
        maintenant = time.monotonic()
        self._precedent = dict(self._stable)

        for nom in self.NOMS:
            niveau = bool(octet & (1 << self._bits[nom]))
            appuye = (not niveau) if cfg.BOUTONS_ACTIFS_BAS else niveau

            if appuye != self._brut[nom]:
                # Le niveau vient de changer : on redémarre le compteur.
                self._brut[nom] = appuye
                self._depuis[nom] = maintenant
            elif (appuye != self._stable[nom]
                  and maintenant - self._depuis[nom] >= cfg.ANTI_REBOND):
                self._stable[nom] = appuye

    def appui(self, nom):
        """True une seule fois, au front d'appui du bouton."""
        return self._stable[nom] and not self._precedent[nom]

    def enfonce(self, nom):
        """True tant que le bouton est maintenu enfoncé."""
        return self._stable[nom]


# ═══════════════════════════════════════════════════════════════════════
#  MACHINE
# ═══════════════════════════════════════════════════════════════════════

class Machine:
    """État des actionneurs et commandes associées.

    L'état complet du port A se déduit de deux variables seulement :
    la position visée du vérin de mise en position, et l'état de la coupe.
    L'octet est recalculé à chaque changement, ce qui rend structurellement
    impossible d'avoir les deux bobines du bistable actives en même temps.
    """

    def __init__(self, mcp):
        self.mcp = mcp
        self.position = "inconnue"        # "inconnue" | "basse" | "haute"
        self.coupe_active = False
        self.initialisee = not cfg.RESET_REQUIS_AU_DEMARRAGE
        self._fin_coupe = 0.0

    # ─────────────────────────────────────────────────────── bas niveau

    def _bobine_courante(self):
        """Bit de la bobine à maintenir, ou None si la position est inconnue."""
        if self.position == "basse":
            return cfg.BIT_POS_DESCENTE
        if self.position == "haute":
            return cfg.BIT_POS_MONTEE
        return None

    def _appliquer(self, bobine, coupe):
        """Compose et écrit l'octet du port A.

        `bobine` vaut au plus un seul numéro de bit : les deux bobines ne
        peuvent donc jamais être commandées ensemble.
        """
        octet = 0
        if bobine is not None:
            octet |= 1 << bobine
        if coupe:
            octet |= 1 << cfg.BIT_EV_COUPE
        self.mcp.ecrire_sorties(octet)

    def tout_couper(self):
        """Remet toutes les sorties à zéro."""
        self.coupe_active = False
        self._fin_coupe = 0.0
        self.mcp.ecrire_sorties(0x00)

    # ────────────────────────────────────────────── vérin de mise en position

    def _commander_position(self, bobine, etat, libelle):
        # Coupure des deux bobines, temps mort, puis alimentation de la bonne.
        self._appliquer(None, self.coupe_active)
        time.sleep(cfg.TEMPS_INTER_BOBINE)
        self._appliquer(bobine, self.coupe_active)
        self.position = etat
        journal(f"POSITION → {libelle} (bobine GPA{bobine} maintenue)")

    def descendre(self):
        if not self.initialisee:
            journal("POSITION refusée — appuyer d'abord sur RESET")
            return
        if self.position == "basse":
            journal("POSITION → déjà en bas, rien à faire")
            return
        self._commander_position(cfg.BIT_POS_DESCENTE, "basse", "BASSE")

    def monter(self):
        self._commander_position(cfg.BIT_POS_MONTEE, "haute", "HAUTE")

    # ────────────────────────────────────────────────────── vérin de coupe

    def lancer_coupe(self):
        if not self.initialisee:
            journal("COUPE refusée — appuyer d'abord sur RESET")
            return
        if self.coupe_active:
            journal("COUPE déjà en cours — appui ignoré")
            return
        if cfg.EXIGER_POSITION_AVANT_COUPE and self.position != "basse":
            journal("COUPE refusée — le vérin de mise en position n'est pas en bas")
            return

        self.coupe_active = True
        self._fin_coupe = time.monotonic() + cfg.TEMPS_DECOUPE
        self._appliquer(self._bobine_courante(), True)
        journal(f"COUPE → ON pendant {cfg.TEMPS_DECOUPE:.1f} s")

    def arreter_coupe(self, motif):
        self.coupe_active = False
        self._fin_coupe = 0.0
        self._appliquer(self._bobine_courante(), False)
        journal(f"COUPE → OFF ({motif})")

    def surveiller_coupe(self):
        """Fin d'impulsion. Appelé à chaque tour de boucle."""
        if self.coupe_active and time.monotonic() >= self._fin_coupe:
            self.arreter_coupe("durée écoulée")

    # ────────────────────────────────────────────────────────────── reset

    def reset(self):
        journal("RESET")
        if self.coupe_active:
            self.arreter_coupe("RESET")
        self.monter()
        self.initialisee = True


# ═══════════════════════════════════════════════════════════════════════
#  BOUCLE PRINCIPALE
# ═══════════════════════════════════════════════════════════════════════

def boucle(mcp):
    boutons = Boutons(mcp)
    machine = Machine(mcp)

    journal("")
    journal("Machine prête — aucune sortie active.")
    if not machine.initialisee:
        journal("Appuyer sur RESET pour remonter le vérin de mise en position.")
    journal("POSITION = abaisser  |  COUPE = couper  |  RESET = tout revenir en position initiale")
    journal("")

    while not _arret_demande:
        boutons.rafraichir()

        # RESET est prioritaire : il n'y a pas d'arrêt d'urgence logiciel,
        # c'est donc la seule commande qui doit passer en toutes circonstances.
        if boutons.appui("reset"):
            machine.reset()
        else:
            if boutons.appui("position"):
                machine.descendre()
            if boutons.appui("coupe"):
                machine.lancer_coupe()

        machine.surveiller_coupe()
        time.sleep(cfg.PERIODE_SCRUTATION)

    return machine


# ═══════════════════════════════════════════════════════════════════════
#  ENTRÉE DU PROGRAMME
# ═══════════════════════════════════════════════════════════════════════

def _handler_arret(sig, _frame):
    """Demande un arrêt propre.

    On ne coupe pas les sorties ici : le travail est fait dans le `finally`
    de main(), pour que le chemin d'arrêt soit unique quelle que soit la
    cause (Ctrl+C, `systemctl stop`, exception).
    """
    global _arret_demande
    _arret_demande = True
    print(f"\n[{time.strftime('%H:%M:%S')}] Signal "
          f"{signal.Signals(sig).name} reçu — arrêt en cours", flush=True)


def main():
    signal.signal(signal.SIGINT, _handler_arret)    # Ctrl+C
    signal.signal(signal.SIGTERM, _handler_arret)   # systemctl stop

    try:
        verifier_config()
    except ValueError as erreur:
        journal(f"ERREUR DE CONFIGURATION : {erreur}")
        return 2

    afficher_config()

    try:
        mcp = MCP23017(cfg.I2C_BUS_ID, cfg.MCP_ADDR,
                       cfg.I2C_RETRIES, cfg.I2C_RETRY_DELAY)
        mcp.configurer()
    except OSError as erreur:
        journal(f"ERREUR : MCP23017 injoignable en 0x{cfg.MCP_ADDR:02X} ({erreur})")
        journal("    vérifier le câblage SDA/SCL/VDD/GND et les straps A0/A1/A2")
        journal("    diagnostic : sudo i2cdetect -y 1")
        return 1

    code_retour = 0
    try:
        boucle(mcp)
        journal("Arrêt demandé")
    except OSError as erreur:
        journal(f"ERREUR DE BUS I2C : {erreur}")
        code_retour = 1
    except Exception as erreur:                      # noqa: BLE001
        journal(f"ERREUR INATTENDUE : {erreur!r}")
        code_retour = 1
    finally:
        # Chemin d'arrêt unique. Le try imbriqué évite qu'une panne de bus
        # masque l'erreur d'origine et empêche la fermeture du bus.
        try:
            mcp.ecrire_sorties(0x00)
            journal("Toutes les sorties remises à zéro")
        except OSError as erreur:
            journal(f"ATTENTION : impossible de remettre les sorties à zéro ({erreur})")
            code_retour = 1
        mcp.close()
        journal("Arrêt complet")

    return code_retour


if __name__ == "__main__":
    sys.exit(main())
