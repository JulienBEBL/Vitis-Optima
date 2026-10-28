# -*- coding: utf-8 -*-
"""
test_8_cycle.py — Cycle complet automatique, les deux postes en même temps.

⚠ CE TEST FAIT TOUT BOUGER : mandrins, lames, les deux moteurs. Arrêt d'urgence
   à portée de main, mains hors de la machine, SANS branche. Tests 4 (EV) et 7
   (rodage) validés.

    python3 tests/test_8_cycle.py

Ce test fait tourner LE VRAI PROGRAMME (la même boucle que main.py, avec ses
interlocks, ses défauts, son buzzer, son journal) et appuie sur les boutons À
TA PLACE — y compris le MAINTIEN des boutons de rotation. Les deux postes font
le même cycle en même temps, chacun de son côté :

    0. ACQUITTEMENT .............. initialisation des deux postes
    puis, à chaque cycle, pour chaque poste :
    1. COUPE, mandrin ouvert ..... doit être REFUSÉE (I3)
    2. BRIDAGE ................... le mandrin se ferme
    3. ROTATION + tenu ROTATION_TENUE_S, puis relâché
    4. ROTATION − tenu 2 × ROTATION_TENUE_S, puis relâché
    5. COUPE ..................... séquence de coupe
    6. BRIDAGE ................... le mandrin s'ouvre
    7. ACQUITTEMENT .............. retour au centre des deux mandrins

Le déplacement manuel du bloc sur le guide de translation n'est pas simulé.
Un appui simulé passe par les mêmes interlocks qu'un vrai : s'il est refusé
(alors qu'il devait être accepté), ou si un poste part en défaut, le test
s'arrête et dit pourquoi. Les VRAIS boutons restent actifs : ne pas y toucher.

Les appuis simulés ne sont pas comptés dans etat/compteurs.json. Le test se termine
seul ; son récapitulatif est ENREGISTRÉ dans logs/cycle_<date>_<heure>.txt.
"""

import sys
import time
from pathlib import Path

import _commun
from _commun import cfg, confirmer, question, titre
from libs import poste as P
from libs.entrees import ACQUITTEMENT, BRIDAGE, COUPE, ROTATION_MOINS, ROTATION_PLUS
from libs.journal import configurer_journal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main as programme                                   # noqa: E402

ROTATION_TENUE_S = 1.5        # durée de maintien de ROTATION +, à chaque cycle
PAUSE_ENTRE_CYCLES_S = 1.0
DELAI_ACTION_MAX_S = 20.0     # au-delà, une action est considérée comme bloquée
CYCLES_PAR_DEFAUT = 3

titre("TEST 8 — CYCLE COMPLET AUTOMATIQUE")
print("  ⚠ Mandrins, lames et moteurs vont bouger. Mains hors de la machine, sans branche.")
reponse = question(f"Nombre de cycles [{CYCLES_PAR_DEFAUT}] ?")
cycles = int(reponse) if reponse.isdigit() and int(reponse) > 0 else CYCLES_PAR_DEFAUT

materiel = _commun.ouvrir(avec_gpio=True)
configurer_journal()
sys.setswitchinterval(cfg.PYTHON_SWITCH_INTERVAL_S)
machine = programme._construire_machine(materiel, compteurs=_commun.CompteursMuets())
postes = list(machine.postes.values())
entrees = machine._entrees

# Appuis simulés : la machine demande « ce bouton vient-il d'être appuyé ? » et
# le poste « ce bouton est-il tenu ? ». On répond oui pour les boutons voulus ;
# les vrais boutons restent lus.
simules = set()
tenus = set()
_vrai_appui, _vrai_tenu = entrees.appui, entrees.tenu


def _appui(nom: str) -> bool:
    if nom in simules:
        simules.discard(nom)
        return True
    return _vrai_appui(nom)


entrees.appui = _appui
entrees.tenu = lambda nom: nom in tenus or _vrai_tenu(nom)


class Arret(Exception):
    pass


def tourner_jusqua(condition, delai_s: float, quoi: str) -> float:
    """Fait tourner la boucle du programme jusqu'à `condition`. Renvoie la durée."""
    debut = time.monotonic()
    prochain = debut
    while True:
        maintenant = time.monotonic()
        machine.tour(maintenant)
        en_defaut = [p.nom for p in postes if p.etat == P.DEFAUT]
        if en_defaut:
            raise Arret(f"{', '.join(en_defaut)} en DÉFAUT pendant : {quoi} (voir la ligne DÉFAUT ci-dessus)")
        if condition():
            return maintenant - debut
        if maintenant - debut > delai_s:
            raise Arret(f"action bloquée après {delai_s:.0f} s : {quoi}")
        prochain += cfg.PERIODE_BOUCLE_S
        reste = prochain - time.monotonic()
        if reste > 0:
            time.sleep(reste)
        else:
            prochain = time.monotonic()


def attendre(duree_s: float, quoi: str = "pause") -> None:
    fin = time.monotonic() + duree_s
    tourner_jusqua(lambda: time.monotonic() >= fin, duree_s + 5, quoi)


def tous_prets() -> bool:
    maintenant = time.monotonic()
    return all(p.etat == P.PRET and maintenant >= p.libre_a for p in postes)


def appuyer_tous(action: str, condition, quoi: str) -> None:
    """Appuie `action` sur les deux postes en même temps, attend `condition` sur chacun."""
    tourner_jusqua(lambda: all(p.refus(action, time.monotonic()) is None for p in postes),
                   DELAI_ACTION_MAX_S, f"attente de l'autorisation — {quoi}")
    simules.update(f"{action}_{p.nom}" for p in postes)
    duree = tourner_jusqua(lambda: all(condition(p) for p in postes) and tous_prets(),
                           DELAI_ACTION_MAX_S, quoi)
    noter(quoi, duree)


def tenir_tous(action: str, duree_s: float, quoi: str) -> None:
    """Maintient le bouton de rotation des deux postes `duree_s`, puis le relâche."""
    tourner_jusqua(tous_prets, DELAI_ACTION_MAX_S, f"attente — {quoi}")
    noms = {f"{action}_{p.nom}" for p in postes}
    debut = {p.nom: p.position for p in postes}
    tenus.update(noms)
    simules.update(noms)
    attendre(0.2, quoi)
    refuses = [p.nom for p in postes if p.etat != P.ROTATION]
    if refuses:
        raise Arret(f"{quoi} : rotation refusée pour {', '.join(refuses)} (motif dans le journal)")
    attendre(duree_s - 0.2, quoi)
    tenus.difference_update(noms)
    duree = tourner_jusqua(tous_prets, DELAI_ACTION_MAX_S, f"arrêt — {quoi}")
    deplacements = ", ".join(f"{p.nom} {(p.position - debut[p.nom]) / cfg.PAS_PAR_DEGRE:+.1f}°"
                             for p in postes)
    noter(f"{quoi} ({deplacements})", duree_s + duree, cle=quoi)


def noter(quoi: str, duree: float, cle: str | None = None) -> None:
    print(f"      ✓ {quoi:58s} {duree:5.2f} s")
    durees.setdefault(cle or quoi, []).append(duree)


durees = {}
conclusion = "non lancé"
faits = 0
try:
    if not confirmer(f"Zone dégagée, sans branche, lancer {cycles} cycle(s) ?"):
        raise SystemExit("  Non lancé.")

    # ── 0. Initialisation ──────────────────────────────────────────────────
    print("\n  Initialisation (ACQUITTEMENT) :")
    tourner_jusqua(lambda: True, 1, "démarrage")
    simules.add(ACQUITTEMENT)
    duree = tourner_jusqua(tous_prets, 120, "initialisation")
    noter("deux postes initialisés et centrés", duree)

    for numero in range(1, cycles + 1):
        print(f"\n  Cycle {numero} / {cycles} :")
        debut_cycle = time.monotonic()

        motifs = [p.refus(COUPE, time.monotonic()) for p in postes]
        if not all(m and m.startswith("I3") for m in motifs):
            raise Arret(f"COUPE mandrin ouvert devait être refusée (I3) : {motifs}")
        simules.update(f"{COUPE}_{p.nom}" for p in postes)
        attendre(0.2, "coupe mandrin ouvert")
        if not all(p.etat == P.PRET and not p.ev_coupe for p in postes):
            raise Arret("une coupe est partie mandrin ouvert")
        print(f"      ✓ {'coupe mandrin ouvert refusée (I3)':58s}")

        appuyer_tous(BRIDAGE, lambda p: p.mandrin_ferme, "fermeture des mandrins")
        tenir_tous(ROTATION_PLUS, ROTATION_TENUE_S, "ROTATION + tenue")
        tenir_tous(ROTATION_MOINS, 2 * ROTATION_TENUE_S, "ROTATION − tenue")
        appuyer_tous(COUPE, lambda p: not p.ev_coupe, "coupe")
        appuyer_tous(BRIDAGE, lambda p: not p.mandrin_ferme, "ouverture des mandrins")

        tourner_jusqua(tous_prets, DELAI_ACTION_MAX_S, "attente — recentrage")
        simules.add(ACQUITTEMENT)
        tourner_jusqua(lambda: all(p.etat == P.RECENTRAGE for p in postes) or tous_prets(), 2,
                       "départ du recentrage")
        duree = tourner_jusqua(tous_prets, DELAI_ACTION_MAX_S, "recentrage")
        noter("recentrage (ACQUITTEMENT) : " + ", ".join(f"{p.nom} {p.degres(p.position)}" for p in postes),
              duree, cle="recentrage (ACQUITTEMENT)")

        faits += 1
        print(f"      cycle {numero} terminé en {time.monotonic() - debut_cycle:.1f} s")
        if numero < cycles:
            attendre(PAUSE_ENTRE_CYCLES_S)
    conclusion = "sans défaut ni refus inattendu"
    print(f"\n  {faits} cycle(s) complet(s), {conclusion}.")
except Arret as arret:
    conclusion = f"✗ ARRÊT : {arret}"
    print(f"\n  {conclusion}")
except KeyboardInterrupt:
    conclusion = "interrompu"
    print("\n  Interrompu.")
finally:
    tenus.clear()
    machine.arreter()
    materiel.fermer()
    if durees:
        lignes = ["┌─ RÉCAPITULATIF À M'ENVOYER " + "─" * 46,
                  f"│ {time.strftime('%Y-%m-%d %H:%M:%S')} — {faits} cycle(s) complet(s) sur {cycles} demandé(s)",
                  f"│ fin : {conclusion}",
                  "│",
                  "│ action                                          fois   durée moy.   min / max"]
        for quoi, liste in durees.items():
            lignes.append(f"│ {quoi:46s} {len(liste):^5d}  {sum(liste) / len(liste):6.2f} s   "
                          f"{min(liste):5.2f} / {max(liste):5.2f} s")
        lignes.append("└" + "─" * 73)
        print()
        for ligne in lignes:
            print("  " + ligne)
        fichier = _commun.fichier_resultat("cycle")
        _commun.enregistrer(fichier, lignes)
        print(f"  Enregistré dans : {fichier}")
    print("  Relais à 0, moteurs libres.\n")
