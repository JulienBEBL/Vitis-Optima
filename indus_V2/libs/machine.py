# -*- coding: utf-8 -*-
"""
machine.py — Coordinateur : état global, initialisation, défauts, règles entre postes.

LOGIQUE.md § 3.1, § 4.1, § 5 et § 6.

Répartition stricte :
  - le POSTE décide de son bridage, de sa coupe, de son axe et de ses propres
    interlocks (I2 à I6) ;
  - le COORDINATEUR décide de l'état global, de l'initialisation, du défaut et
    des règles entre postes (I1, I7, I8). Il autorise ou refuse une demande ;
    il ne la pilote pas. Un poste n'appelle jamais l'autre.

C'est aussi le coordinateur qui compose l'octet des relais : à partir des
variables ev_* des postes en MARCHE, et à 0 dans tous les autres états.

Origine : Vitis V1 indus/vitis_optima.py — fonction `boucle()` (une lecture
par tour, priorité de RESET) et méthode `Machine._appliquer()` (octet composé
depuis l'état, jamais de lecture-modification-écriture).
"""

from __future__ import annotations

import logging

import config as cfg
from libs.materiel import PORT_A, Buzzer, Materiel
from libs.entrees import Entrees
from libs.journal import Compteurs
from libs.moteur import PortsDrivers
from libs.poste import (BRIDAGE, COUPE, DESCRIPTION_DEFAUTS, POSITION, PRET_COUPE,
                        Defaut, Poste)

log = logging.getLogger("vitis")

# États globaux
ATTENTE_ACQUITTEMENT = "ATTENTE_ACQUITTEMENT"
INITIALISATION = "INITIALISATION"
MARCHE = "MARCHE"
DEFAUT = "DEFAUT"


class Machine:

    def __init__(self, materiel: Materiel, entrees: Entrees, postes: dict[str, Poste],
                 drivers: PortsDrivers, buzzer: Buzzer, compteurs: Compteurs) -> None:
        self._materiel = materiel
        self._entrees = entrees
        self._drivers = drivers
        self._buzzer = buzzer
        self._compteurs = compteurs

        self._postes = (postes[cfg.POSTE_MERE], postes[cfg.POSTE_FILLE])
        self.maitre = postes[cfg.MOTEUR_MAITRE]
        self.esclave = postes[cfg.POSTE_FILLE if cfg.MOTEUR_MAITRE == cfg.POSTE_MERE
                              else cfg.POSTE_MERE]
        self._bits_ev = {cfg.POSTE_MERE: (cfg.EV_BRIDAGE_MERE, cfg.EV_COUPE_MERE),
                         cfg.POSTE_FILLE: (cfg.EV_BRIDAGE_FILLE, cfg.EV_COUPE_FILLE)}

        self.etat = ATTENTE_ACQUITTEMENT
        self._phase_init = None                 # "esclave" | "maitre"
        self._prochaine_verif_mcp = 0.0
        self._ecarts_mcp: dict[int, int] = {}   # adresse → relectures fausses consécutives
        self._bus_en_erreur = False

        log.info("Maître : %s — esclave : %s", self.maitre.nom, self.esclave.nom)
        log.info("En attente d'ACQUITTEMENT pour initialiser")

    @property
    def mouvement_en_cours(self) -> bool:
        return any(poste.en_mouvement for poste in self._postes)

    # ═══════════════════════════════════════════════════════════════════════
    #  UN TOUR DE BOUCLE  (LOGIQUE.md § 9)
    # ═══════════════════════════════════════════════════════════════════════

    def tour(self, maintenant: float) -> None:
        try:
            self._entrees.rafraichir(maintenant)
            if self._bus_en_erreur:
                log.info("Bus I2C rétabli")
                self._bus_en_erreur = False

            if self.etat in (INITIALISATION, MARCHE):
                for poste in self._postes:
                    poste.avancer(maintenant)
                if self.etat == INITIALISATION:
                    self._avancer_initialisation(maintenant)

            self._traiter_boutons(maintenant)
            self._ecrire_sorties()
            self._verifier_mcp(maintenant)

        except Defaut as defaut:
            self._declencher_defaut(defaut.code, defaut.detail)
        except OSError as erreur:
            # Politique I2C : le driver a déjà retenté I2C_RETRIES fois. Au-delà,
            # c'est un défaut. En DÉFAUT, on continue d'essayer à chaque tour
            # (pour lire ACQUITTEMENT), sans inonder le journal.
            if self.etat != DEFAUT:
                self._declencher_defaut("D6", str(erreur))
            elif not self._bus_en_erreur:
                log.error("Bus I2C toujours en erreur : %s", erreur)
            self._bus_en_erreur = True

        self._buzzer.avancer(maintenant)
        self._compteurs.sauver_si_du(maintenant, autorise=not self.mouvement_en_cours)

    # ═══════════════════════════════════════════════════════════════════════
    #  BOUTONS ET INTERLOCKS
    # ═══════════════════════════════════════════════════════════════════════

    def _traiter_boutons(self, maintenant: float) -> None:
        if self._entrees.appui("acquittement"):
            if self.etat in (ATTENTE_ACQUITTEMENT, DEFAUT):
                self._accepter("acquittement")
                self._entrer_initialisation(maintenant)
            else:
                self._refuser("acquittement", f"sans effet en {self.etat}")

        for poste in self._postes:
            for action in (BRIDAGE, COUPE, POSITION):
                nom = f"{action}_{poste.nom}"
                if not self._entrees.appui(nom):
                    continue
                motif = self._motif_refus(poste, action, maintenant)
                if motif:
                    self._refuser(nom, motif)
                    continue
                self._accepter(nom)
                if action == BRIDAGE:
                    poste.lancer_bridage(maintenant)
                elif action == COUPE:
                    poste.lancer_coupe(maintenant)
                else:
                    poste.lancer_mouvement(maintenant)

    def _motif_refus(self, poste: Poste, action: str, maintenant: float) -> str | None:
        """Interlocks dans l'ordre de LOGIQUE.md § 5. Le premier qui échoue gagne."""
        if self.etat != MARCHE:
            return f"I1 — machine en {self.etat}"
        motif = poste.refus_local(action, maintenant)
        if motif or action != POSITION:
            return motif

        aller = poste.etat == PRET_COUPE
        if aller and poste is self.esclave:
            if self.maitre.position != cfg.POSITION_LIGATURAGE:
                return f"I7 — le maître ({self.maitre.nom}) doit être en ligaturage d'abord"
            if maintenant < self.maitre.arrive_a + cfg.RETARD_SENS_ALLER_S:
                return "I7 — délai après l'arrivée du maître non écoulé"
        if aller and poste is self.maitre and self.esclave.position != cfg.POSITION_COUPE:
            # Garde défensive : l'esclave hors position coupe avec le maître en
            # coupe est inatteignable en marche normale (I7 + I8 l'interdisent).
            return f"I7 — l'esclave ({self.esclave.nom}) doit être en position coupe"
        if not aller and poste is self.maitre and self.esclave.position != cfg.POSITION_COUPE:
            return f"I8 — l'esclave ({self.esclave.nom}) doit revenir en position coupe d'abord"
        return None

    def _accepter(self, nom: str) -> None:
        self._compteurs.bouton(nom, accepte=True)
        self._buzzer.bip_court()

    def _refuser(self, nom: str, motif: str) -> None:
        self._compteurs.bouton(nom, accepte=False)
        self._buzzer.bip_refus()
        log.info("Appui %s refusé : %s", nom, motif)

    # ═══════════════════════════════════════════════════════════════════════
    #  INITIALISATION  (esclave puis maître)
    # ═══════════════════════════════════════════════════════════════════════

    def _entrer_initialisation(self, maintenant: float) -> None:
        log.info("Initialisation : référencement %s puis %s", self.esclave.nom, self.maitre.nom)
        self.etat = INITIALISATION
        for poste in self._postes:
            poste.neutraliser()                 # repart d'un état propre
        self._phase_init = "esclave"
        self.esclave.lancer_referencement(maintenant)

    def _avancer_initialisation(self, maintenant: float) -> None:
        if self._phase_init == "esclave" and self.esclave.etat == PRET_COUPE:
            self._phase_init = "maitre"
            self.maitre.lancer_referencement(maintenant)
        if self._phase_init == "maitre" and self.maitre.etat == PRET_COUPE:
            self._phase_init = None
            self.etat = MARCHE
            for poste in self._postes:
                poste.libre_a = maintenant + cfg.TEMPS_GARDE_APRES_ACTION_S
            self._buzzer.double_bip()
            log.info("Machine prête")

    # ═══════════════════════════════════════════════════════════════════════
    #  SORTIES
    # ═══════════════════════════════════════════════════════════════════════

    def _ecrire_sorties(self) -> None:
        """Octet des relais composé depuis l'état, écrit seulement s'il change.

        Hors MARCHE, il vaut 0 quoi que disent les postes. Une écriture ratée
        n'a pas mis l'image à jour : elle est retentée au tour suivant.
        """
        octet = 0x00
        if self.etat == MARCHE:
            for poste in self._postes:
                bit_bridage, bit_coupe = self._bits_ev[poste.nom]
                if poste.ev_bridage:
                    octet |= 1 << bit_bridage
                if poste.ev_coupe:
                    octet |= 1 << bit_coupe
        if octet != self._materiel.relais.image(PORT_A):
            self._materiel.relais.ecrire_port(PORT_A, octet)

        # Au repos et en défaut, les moteurs sont libres. Retenté à chaque tour
        # si l'écriture du défaut a échoué.
        if self.etat in (ATTENTE_ACQUITTEMENT, DEFAUT) and not self._drivers.tous_libres():
            self._drivers.liberer_tous()

    def _verifier_mcp(self, maintenant: float) -> None:
        """D7 : relecture périodique de la configuration des trois MCP."""
        if maintenant < self._prochaine_verif_mcp:
            return
        self._prochaine_verif_mcp = maintenant + cfg.RELECTURE_CONFIG_MCP_PERIODE_S
        for mcp in (self._materiel.relais, self._materiel.drivers, self._materiel.entrees):
            ecarts = mcp.ecarts_config()
            if not ecarts:
                self._ecarts_mcp[mcp.adresse] = 0
                continue
            consecutifs = self._ecarts_mcp.get(mcp.adresse, 0) + 1
            self._ecarts_mcp[mcp.adresse] = consecutifs
            # Déjà en DÉFAUT : on se contente de reconfigurer, pour continuer à
            # lire ACQUITTEMENT. Un seul avertissement par série.
            if consecutifs >= 2 and self.etat != DEFAUT:
                raise Defaut("D7", f"MCP 0x{mcp.adresse:02X} : {', '.join(ecarts)}")
            if consecutifs == 1:
                log.warning("MCP 0x%02X : configuration perdue (%s) — reconfiguration",
                            mcp.adresse, ", ".join(ecarts))
            mcp.configurer()

    # ═══════════════════════════════════════════════════════════════════════
    #  DÉFAUT ET ARRÊT
    # ═══════════════════════════════════════════════════════════════════════

    def _declencher_defaut(self, code: str, detail: str) -> None:
        """Réaction commune à tout défaut (LOGIQUE.md § 6). Global : les deux postes."""
        log.error("DÉFAUT %s — %s : %s", code, DESCRIPTION_DEFAUTS[code], detail)
        for poste in self._postes:
            poste.neutraliser()
        for poste in self._postes:
            if not poste.axe.attendre_fin(cfg.ARRET_THREAD_MAX_S):
                log.error("%s : le thread d'impulsions ne s'arrête pas", poste.nom)
        try:
            self._materiel.relais.ecrire_port(PORT_A, 0x00)
        except OSError as erreur:
            log.error("Relais non remis à 0 (%s) — nouvelle tentative à chaque tour", erreur)
        try:
            self._drivers.liberer_tous()
        except OSError as erreur:
            log.error("ENA non remis à « libre » (%s) — nouvelle tentative à chaque tour", erreur)
        self.etat = DEFAUT
        self._phase_init = None
        self._buzzer.bip_defaut()
        self._compteurs.defaut(code)
        self._compteurs.sauver()
        log.info("Appuyer sur ACQUITTEMENT pour relancer l'initialisation")

    def arreter(self) -> None:
        """Arrêt du programme : axes arrêtés, buzzer coupé, compteurs sauvés.

        Relais et ENA sont remis en sécurité ensuite par Materiel.fermer().
        """
        for poste in self._postes:
            poste.neutraliser()
        for poste in self._postes:
            if not poste.axe.attendre_fin(cfg.ARRET_THREAD_MAX_S):
                log.error("%s : le thread d'impulsions ne s'arrête pas", poste.nom)
        self._buzzer.couper()
        self._compteurs.sauver()
