# -*- coding: utf-8 -*-
"""
test_10_modes.py — La machine complète : EV, moteurs, boutons, en trois modes.

⚠ CE TEST FAIT TOUT BOUGER : mandrins, lames, moteurs. Arrêt d'urgence à portée de
   main. test_4 (attribution des relais) fait d'abord. Sans air comprimé, on entend
   seulement les relais : c'est le bon premier essai.

Lancer depuis Geany (F5). Le menu demande le mode, les postes, puis l'angle et le
nombre de cycles. C'est LE VRAI PROGRAMME qui tourne (la boucle de main.py, ses
interlocks, ses défauts, son buzzer, son journal).

MANU — chaque bouton fait une seule action, rien ne s'enchaîne, comme main.py.
  ACQUITTEMENT initialise, puis ramène au centre. Fin après INACTIVITE_MANU_S sans
  rien toucher.

SEMI-AUTO — le programme enchaîne le cycle, mais attend un appui sur ACQUITTEMENT
  avant chaque étape. Tu avances et recules le bloc à la main entre deux étapes.
  Les autres boutons sont ignorés. Fin après INACTIVITE_SEMI_S sans appui (le
  mandrin s'ouvre alors : garder la branche en main).

AUTO — le cycle s'enchaîne seul, SANS branche et sans bouger le bloc. Les autres
  boutons sont ignorés. ACQUITTEMENT arrête proprement : fin de l'étape en cours,
  mandrins ouverts, retour au centre.

Le cycle de SEMI-AUTO et AUTO, pour chaque poste choisi, en même temps :
    1. BRIDAGE ....... le mandrin se ferme (avant : COUPE refusée mandrin ouvert)
    2. ROTATION ...... ANGLE depuis le centre, en maintenant le bouton comme un
                       opérateur : + aux cycles impairs, − aux cycles pairs
    3. COUPE ......... séquence de coupe
    4. BRIDAGE ....... le mandrin s'ouvre
    5. ACQUITTEMENT .. retour au centre
Après le dernier cycle : CONTRÔLE DE POSITION. Aller sur chaque butée et comparer la
position comptée : un écart montre des pas perdus aux arrêts nets en pleine vitesse.

⚠ Aucun capteur ne confirme que le mandrin est fermé : la coupe se fie à la commande
   et à TEMPS_MANOEUVRE_MANDRIN_S. Une panne d'air n'est PAS détectée.

Fin : RÉCAPITULATIF, ENREGISTRÉ dans logs/modes_<date>_<heure>.txt. Moteurs sous
tension pendant tout le test, libérés seulement à la sortie du programme.
"""

import sys
import time
from pathlib import Path

import _commun
from _commun import cfg, confirmer, menu, nombre, titre
from libs import poste as P
from libs.entrees import ACQUITTEMENT, BRIDAGE, COUPE, ROTATION_MOINS, ROTATION_PLUS
from libs.journal import configurer_journal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main as programme                                   # noqa: E402

MANU, SEMI, AUTO = "manu", "semi-auto", "auto"
INACTIVITE_MANU_S = 300.0
INACTIVITE_SEMI_S = 300.0
ANGLE_PAR_DEFAUT_DEG = 45
CYCLES_PAR_DEFAUT = 3
PAUSE_ENTRE_CYCLES_S = 1.0
DELAI_ACTION_MAX_S = 30.0       # au-delà, une action est considérée comme bloquée
DELAI_INIT_MAX_S = 150.0
PERIODE_AFFICHAGE_S = 0.05


class Compteurs(_commun.CompteursMuets):
    """Rien dans etat/compteurs.json, mais gardés pour le récapitulatif."""

    def __init__(self) -> None:
        self.acceptes = 0
        self.refuses = 0
        self.defauts = []
        self.dernier_appui = time.monotonic()

    def bouton(self, _nom: str, accepte: bool) -> None:
        self.dernier_appui = time.monotonic()
        if accepte:
            self.acceptes += 1
        else:
            self.refuses += 1

    def defaut(self, poste: str, code: str) -> None:
        self.defauts.append(f"{code} {poste}")


class Fin(Exception):
    """Fin du test : arrêt demandé, plus aucun appui, ou action en échec."""


titre("TEST 10 — MANU, SEMI-AUTO, AUTO")
mode = {"m": MANU, "s": SEMI, "a": AUTO}[menu("Quel mode ?", {
    "m": "MANU : chaque bouton fait une action",
    "s": "SEMI-AUTO : ACQUITTEMENT avant chaque étape",
    "a": "AUTO : cycle enchaîné, sans branche"}, "m")]
noms = _commun.choisir_postes("Postes ? (seulement ceux qui sont branchés)")
angle_deg, cycles = 0.0, 0
if mode != MANU:
    angle_max = min(cfg.PLAGE_NOMINALE_DEG[n] / 2 - cfg.PLAGE_TOLERANCE_DEG - cfg.ZONE_APPROCHE_BUTEE_DEG
                    for n in noms)
    angle_deg = float(nombre(f"Angle de rotation depuis le centre, en degrés (max {angle_max:.0f})",
                             ANGLE_PAR_DEFAUT_DEG))
    if angle_deg > angle_max:
        print(f"    limité à {angle_max:.0f}°")
        angle_deg = angle_max
    cycles = nombre("Nombre de cycles", CYCLES_PAR_DEFAUT)

materiel = _commun.ouvrir(avec_gpio=True)
configurer_journal()
sys.setswitchinterval(cfg.PYTHON_SWITCH_INTERVAL_S)
compteurs = Compteurs()
machine = programme._construire_machine(materiel, compteurs=compteurs)
# Un poste non branché est retiré : boutons ignorés, relais à 0, moteur jamais excité.
for nom in [n for n in machine.postes if n not in noms]:
    del machine.postes[nom]
postes = list(machine.postes.values())
entrees = machine._entrees

# SEMI-AUTO et AUTO : la machine ne voit plus que les appuis du programme. Le vrai
# ACQUITTEMENT est lu à part (`vrai_appui`), pour passer à l'étape suivante ou arrêter.
simules, tenus = set(), set()
vrai_appui = entrees.appui
acquittement = {"vu": False}


def _appui(nom: str) -> bool:
    if nom in simules:
        simules.discard(nom)
        return True
    return False


if mode != MANU:
    entrees.appui = _appui
    entrees.tenu = lambda nom: nom in tenus

durees, ecarts_controle = {}, {}
prochain_affichage = {"t": 0.0}


def afficher() -> None:
    """Une ligne d'état, moins de 80 caractères (Geany la répète au-delà)."""
    maintenant = time.monotonic()
    if maintenant < prochain_affichage["t"]:
        return
    prochain_affichage["t"] = maintenant + PERIODE_AFFICHAGE_S
    colonnes = [f"{p.nom[0].upper()} {p.degres(p.position):>7s} {p.etat[:6]:6s} "
                f"{'FERME' if p.mandrin_ferme else 'ouvert'}" for p in postes]
    print("\r    " + "  ".join(colonnes) + "   ", end="", flush=True)


def tourner_jusqua(condition, delai_s: float, quoi: str, attente_operateur: bool = False) -> float:
    """Fait tourner la boucle du programme jusqu'à `condition`. Renvoie la durée."""
    debut = time.monotonic()
    prochain = debut
    while True:
        maintenant = time.monotonic()
        machine.tour(maintenant)
        if vrai_appui(ACQUITTEMENT):
            acquittement["vu"] = True
        en_defaut = [p.nom for p in postes if p.etat == P.DEFAUT]
        if en_defaut:
            raise Fin(f"{', '.join(en_defaut)} en DÉFAUT pendant : {quoi}")
        afficher()
        if condition():
            return maintenant - debut
        if maintenant - debut > delai_s:
            raise Fin(f"aucun appui depuis {delai_s:.0f} s : {quoi}" if attente_operateur
                      else f"action bloquée après {delai_s:.0f} s : {quoi}")
        prochain += cfg.PERIODE_BOUCLE_S
        reste = prochain - time.monotonic()
        if reste > 0:
            time.sleep(reste)
        else:
            prochain = time.monotonic()


def tous_prets() -> bool:
    maintenant = time.monotonic()
    return all(p.etat == P.PRET and maintenant >= p.libre_a for p in postes)


def noter(quoi: str, duree: float, detail: str = "") -> None:
    print(f"\r      ✓ {quoi:30s} {duree:6.2f} s  {detail}".ljust(76))
    durees.setdefault(quoi, []).append(duree)


# ── Les actions du cycle ───────────────────────────────────────────────────

def appuyer(action: str, condition) -> None:
    """Le même bouton sur tous les postes, en même temps : passe par les interlocks."""
    tourner_jusqua(tous_prets, DELAI_ACTION_MAX_S, f"attente avant {action}")
    motifs = [m for m in (p.refus(action, time.monotonic()) for p in postes) if m]
    if motifs:
        raise Fin(f"{action} refusé : {motifs[0]}")
    simules.update(f"{action}_{p.nom}" for p in postes)
    tourner_jusqua(lambda: all(condition(p) for p in postes) and tous_prets(), DELAI_ACTION_MAX_S, action)


def verifier_coupe_refusee() -> None:
    """Interlock I3 : COUPE appuyé mandrin ouvert ne doit rien faire."""
    tourner_jusqua(tous_prets, DELAI_ACTION_MAX_S, "attente avant contrôle I3")
    motifs = [p.refus(COUPE, time.monotonic()) for p in postes]
    if not all(m and m.startswith("I3") for m in motifs):
        raise Fin(f"COUPE mandrin ouvert devait être refusée (I3) : {motifs}")
    simules.update(f"{COUPE}_{p.nom}" for p in postes)
    fin = time.monotonic() + 0.2
    tourner_jusqua(lambda: time.monotonic() >= fin, 2, "contrôle I3")
    if any(p.etat != P.PRET or p.ev_coupe for p in postes):
        raise Fin("une coupe est partie mandrin ouvert")


def tourner_angle(action: str) -> str:
    """Maintient le bouton de rotation de chaque poste, le relâche à l'angle voulu."""
    tourner_jusqua(tous_prets, DELAI_ACTION_MAX_S, f"attente avant {action}")
    objectif = round(angle_deg * cfg.PAS_PAR_DEGRE)
    depart = {p.nom: p.position for p in postes}
    boutons = {p.nom: f"{action}_{p.nom}" for p in postes}
    tenus.update(boutons.values())
    simules.update(boutons.values())

    def fini() -> bool:
        for p in postes:
            if boutons[p.nom] in tenus and abs(p.position - depart[p.nom]) >= objectif:
                tenus.discard(boutons[p.nom])
        return not tenus and tous_prets()

    try:
        tourner_jusqua(fini, DELAI_ACTION_MAX_S, action)
    finally:
        tenus.clear()
    return ", ".join(f"{p.nom[0].upper()} {(p.position - depart[p.nom]) / cfg.PAS_PAR_DEGRE:+.1f}°" for p in postes)


def recentrer() -> str:
    tourner_jusqua(tous_prets, DELAI_ACTION_MAX_S, "attente avant recentrage")
    simules.add(ACQUITTEMENT)
    tourner_jusqua(lambda: not simules and (tous_prets() or any(p.etat == P.RECENTRAGE for p in postes)),
                   2, "départ du recentrage")
    tourner_jusqua(tous_prets, DELAI_ACTION_MAX_S, "recentrage")
    return ", ".join(f"{p.nom[0].upper()} {p.degres(p.position)}" for p in postes)


def aller_sur_butee(sens: str) -> str:
    tourner_jusqua(tous_prets, DELAI_ACTION_MAX_S, f"attente avant butée {sens}")
    for p in postes:
        p.lancer_rotation(sens)
    tourner_jusqua(lambda: all(p.etat == P.PRET for p in postes), 60, f"butée {sens}")
    for p in postes:
        ecarts_controle.setdefault(p.nom, []).append((p.dernier_ecart_recalage or 0) / cfg.PAS_PAR_DEGRE)
    return ", ".join(f"{p.nom[0].upper()} {ecarts_controle[p.nom][-1]:+.2f}°" for p in postes)


def initialiser() -> str:
    tourner_jusqua(lambda: True, 1, "démarrage")
    simules.add(ACQUITTEMENT)
    tourner_jusqua(tous_prets, DELAI_INIT_MAX_S, "initialisation")
    return ", ".join(f"{p.nom[0].upper()} {p.degres(p.plage)}" for p in postes)


# ── Déroulé de SEMI-AUTO et AUTO ───────────────────────────────────────────

def etape(texte: str, consigne: str, action) -> None:
    """Une étape : en SEMI-AUTO, attend ACQUITTEMENT ; en AUTO, vérifie qu'on continue."""
    if mode == SEMI:
        print(f"\r\n    → {texte} : {consigne}".ljust(76))
        print("      ACQUITTEMENT pour lancer")
        acquittement["vu"] = False
        tourner_jusqua(lambda: acquittement["vu"], INACTIVITE_SEMI_S, texte, attente_operateur=True)
    elif acquittement["vu"]:
        raise Fin("ACQUITTEMENT : arrêt demandé")
    debut = time.monotonic()
    detail = action()
    noter(texte, time.monotonic() - debut, detail or "")


def cycle(numero: int) -> None:
    print(f"\n  Cycle {numero} / {cycles} :")
    verifier_coupe_refusee()
    bouton_rotation = ROTATION_PLUS if numero % 2 else ROTATION_MOINS
    etape("fermeture du mandrin", "branche en place, mains dégagées",
          lambda: appuyer(BRIDAGE, lambda p: p.mandrin_ferme))
    etape("rotation", f"bloc avancé si besoin ; {angle_deg:.0f}° ({bouton_rotation})",
          lambda: tourner_angle(bouton_rotation))
    etape("coupe", "bloc en position, mains dégagées, la lame va descendre",
          lambda: appuyer(COUPE, lambda p: not p.ev_coupe))
    etape("ouverture du mandrin", "bloc reculé, tiens la branche",
          lambda: appuyer(BRIDAGE, lambda p: not p.mandrin_ferme))
    etape("retour au centre", "mandrin ouvert", recentrer)


def controle_position() -> None:
    print("\n  Contrôle de position :")
    etape("butée horaire", "le mandrin va sur sa butée", lambda: aller_sur_butee(cfg.SENS_HORAIRE))
    etape("butée antihoraire", "le mandrin va sur l'autre butée", lambda: aller_sur_butee(cfg.SENS_ANTIHORAIRE))
    etape("retour au centre", "fin du contrôle", recentrer)


def repli() -> None:
    """AUTO arrêté par ACQUITTEMENT : mandrins ouverts, retour au centre."""
    if any(p.mandrin_ferme for p in postes):
        appuyer(BRIDAGE, lambda p: not p.mandrin_ferme)
    recentrer()


def manu() -> None:
    print("\n  Tous les boutons sont actifs. ACQUITTEMENT : initialisation, puis retour au centre.")
    print(f"  Fin après {INACTIVITE_MANU_S:.0f} s sans rien toucher (position, état, mandrin ci-dessous).\n")
    compteurs.dernier_appui = time.monotonic()

    def inactif() -> bool:
        if any(p.etat in (P.INITIALISATION, P.ROTATION, P.RECENTRAGE) for p in postes):
            compteurs.dernier_appui = time.monotonic()
        return time.monotonic() - compteurs.dernier_appui > INACTIVITE_MANU_S

    machine_tourne = True
    prochain = time.monotonic()
    while machine_tourne:
        machine.tour(time.monotonic())
        afficher()
        machine_tourne = not inactif()
        prochain += cfg.PERIODE_BOUCLE_S
        reste = prochain - time.monotonic()
        if reste > 0:
            time.sleep(reste)
        else:
            prochain = time.monotonic()
    print()


# ── Programme ──────────────────────────────────────────────────────────────

conclusion = "non lancé"
faits = 0
try:
    avertissement = {MANU: "Zone dégagée, lancer ?",
                     SEMI: "Arrêt d'urgence à portée de main, lancer ?",
                     AUTO: f"SANS branche, mains hors de la machine, lancer {cycles} cycle(s) ?"}[mode]
    if not confirmer(avertissement):
        raise Fin("non lancé")
    if mode == MANU:
        manu()
        conclusion = f"plus rien touché depuis {INACTIVITE_MANU_S:.0f} s"
    else:
        print(f"\n  Mode {mode}, {cycles} cycle(s), {angle_deg:.0f}° depuis le centre.")
        if mode == AUTO:
            print("  ACQUITTEMENT : arrêt propre à la fin de l'étape en cours.")
        etape("initialisation", "les mandrins vont chercher leurs butées", initialiser)
        for numero in range(1, cycles + 1):
            cycle(numero)
            faits = numero
            if mode == AUTO and numero < cycles:
                fin_pause = time.monotonic() + PAUSE_ENTRE_CYCLES_S
                tourner_jusqua(lambda: time.monotonic() >= fin_pause, PAUSE_ENTRE_CYCLES_S + 5, "pause")
        controle_position()
        conclusion = "cycles terminés, sans défaut ni refus inattendu"
except Fin as fin:
    conclusion = str(fin)
    if mode == AUTO and acquittement["vu"]:
        try:
            repli()
            conclusion += " — mandrins ouverts, retour au centre"
        except Fin as echec:
            conclusion += f" — repli incomplet : {echec}"
except KeyboardInterrupt:
    conclusion = "interrompu"
finally:
    tenus.clear()
    # La sécurité d'abord : si la fenêtre est fermée, un print() peut échouer ensuite.
    retards = ", ".join(f"{p.nom} {p.axe.retard_max_s * 1000:.1f} ms" for p in postes)
    machine.arreter()
    materiel.fermer()
    lignes = ["┌─ RÉCAPITULATIF À M'ENVOYER " + "─" * 46,
              f"│ {time.strftime('%Y-%m-%d %H:%M:%S')} — mode {mode}, postes : {', '.join(noms)}",
              f"│ croisière {cfg.VITESSE_CROISIERE_DEG_S:.0f}°/s, rampe {cfg.DUREE_RAMPE_ROTATION_S:.1f} s, "
              f"passe rapide {cfg.VITESSE_RECHERCHE_RAPIDE_DEG_S:.0f}°/s, mandrin "
              f"{cfg.TEMPS_MANOEUVRE_MANDRIN_S:.2f} s, coupe {cfg.TEMPS_COUPE_S:.2f} s",
              f"│ fin : {conclusion}"]
    if mode == MANU:
        lignes.append(f"│ boutons : {compteurs.acceptes} acceptés, {compteurs.refuses} refusés")
    else:
        lignes.append(f"│ {faits} cycle(s) complet(s) sur {cycles}, angle {angle_deg:.0f}°")
    lignes.append("│ défauts : " + (", ".join(compteurs.defauts) or "aucun"))
    lignes.append(f"│ retard max des impulsions : {retards}")
    for nom, ecarts in ecarts_controle.items():
        lignes.append(f"│ contrôle de position {nom} : " + ", ".join(f"{e:+.2f}°" for e in ecarts))
    if durees:
        lignes += ["│", "│ étape                           fois   durée moy.   min / max"]
        for quoi, liste in durees.items():
            lignes.append(f"│ {quoi:30s} {len(liste):^5d}  {sum(liste) / len(liste):6.2f} s   "
                          f"{min(liste):5.2f} / {max(liste):5.2f} s")
    lignes.append("└" + "─" * 73)
    print("\n")
    for ligne in lignes:
        print("  " + ligne)
    fichier = _commun.fichier_resultat("modes")
    _commun.enregistrer(fichier, lignes)
    print(f"  Enregistré dans : {fichier}")
    print("  Relais à 0, moteurs libres.\n")
