# -*- coding: utf-8 -*-
"""
test_8_cycle.py — Cycle complet automatique : toutes les actions, dans le bon ordre.

⚠ CE TEST FAIT TOUT BOUGER : pinces, lames, les deux moteurs. Arrêt d'urgence à
   portée de main, mains hors de la machine. Tests 4 (EV) et 7 (rodage) validés.

    python3 tests/test_8_cycle.py

Ce test fait tourner LE VRAI PROGRAMME (la même machine à états que main.py,
avec ses interlocks, ses défauts, son buzzer, son journal) et appuie sur les
boutons À TA PLACE, dans l'ordre d'un cycle de greffage :

    0. ACQUITTEMENT ............ initialisation, les deux axes en position coupe
    puis, à chaque cycle :
    1. BRIDAGE maître, BRIDAGE esclave ......... les deux pinces se ferment
    2. COUPE maître et COUPE esclave ........... les lames coupent (ensemble)
    3. POSITION maître ......................... le maître part en ligaturage
    4. POSITION esclave ........................ puis l'esclave (après RETARD_SENS_ALLER_S)
    5. pause TEMPS_LIGATURAGE_S ................ (le temps de ligaturer)
    6. POSITION esclave ........................ l'esclave revient en coupe le premier
    7. POSITION maître ......................... puis le maître
    8. BRIDAGE maître, BRIDAGE esclave ......... les deux pinces s'ouvrent

Un appui simulé passe par les mêmes interlocks qu'un vrai : s'il est refusé, ou
si la machine part en défaut, le test s'arrête et dit pourquoi. Les VRAIS
boutons restent actifs pendant le test : ne pas y toucher.

Les appuis simulés sont comptés comme des appuis dans etat/compteurs.json.
"""

import sys
import time
from pathlib import Path

import _commun
from _commun import cfg, confirmer, question, titre
from libs import machine as M
from libs import poste as P
from libs.journal import configurer_journal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main as programme                                   # noqa: E402

TEMPS_LIGATURAGE_S = 2.0      # pause en position ligaturage, à chaque cycle
PAUSE_ENTRE_CYCLES_S = 1.0
DELAI_ACTION_MAX_S = 15.0     # au-delà, une action est considérée comme bloquée
CYCLES_PAR_DEFAUT = 3

titre("TEST 8 — CYCLE COMPLET AUTOMATIQUE")
print("  ⚠ Pinces, lames et moteurs vont bouger. Mains hors de la machine.")
reponse = question(f"Nombre de cycles [{CYCLES_PAR_DEFAUT}] ?")
cycles = int(reponse) if reponse.isdigit() and int(reponse) > 0 else CYCLES_PAR_DEFAUT

materiel = _commun.ouvrir(avec_gpio=True)
configurer_journal()
sys.setswitchinterval(cfg.PYTHON_SWITCH_INTERVAL_S)
machine = programme._construire_machine(materiel)
maitre, esclave = machine.maitre, machine.esclave

# Appuis simulés : la machine demande « ce bouton vient-il d'être appuyé ? »,
# on répond oui une fois pour le bouton voulu. Les vrais boutons restent lus.
simules = set()
_vrai_appui = machine._entrees.appui


def _appui(nom: str) -> bool:
    if nom in simules:
        simules.discard(nom)
        return True
    return _vrai_appui(nom)


machine._entrees.appui = _appui


class Arret(Exception):
    pass


def tourner_jusqua(condition, delai_s: float, quoi: str) -> float:
    """Fait tourner la boucle du programme jusqu'à `condition`. Renvoie la durée."""
    debut = time.monotonic()
    prochain = debut
    while True:
        maintenant = time.monotonic()
        machine.tour(maintenant)
        if machine.etat == M.DEFAUT:
            raise Arret(f"la machine est passée en DÉFAUT pendant : {quoi} (voir la ligne DÉFAUT ci-dessus)")
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


def attendre(duree_s: float) -> None:
    fin = time.monotonic() + duree_s
    tourner_jusqua(lambda: time.monotonic() >= fin, duree_s + 5, "pause")


def appuyer(poste, action: str, condition, quoi: str) -> float:
    """Attend que le programme accepte l'action (interlocks), appuie, attend le résultat."""
    tourner_jusqua(lambda: machine._motif_refus(poste, action, time.monotonic()) is None,
                   DELAI_ACTION_MAX_S, f"attente de l'autorisation — {quoi}")
    simules.add(f"{action}_{poste.nom}")
    duree = tourner_jusqua(condition, DELAI_ACTION_MAX_S, quoi)
    print(f"      ✓ {quoi:46s} {duree:5.2f} s")
    durees.setdefault(quoi, []).append(duree)
    return duree


def libre(poste, etat: str):
    """Condition : le poste est revenu dans `etat` (action terminée)."""
    return lambda: poste.etat == etat


durees = {}
faits = 0
try:
    if not confirmer(f"Zone dégagée, lancer {cycles} cycle(s) (maître = {maitre.nom}) ?"):
        raise SystemExit("  Non lancé.")

    # ── 0. Initialisation ──────────────────────────────────────────────────
    print("\n  Initialisation (ACQUITTEMENT) :")
    tourner_jusqua(lambda: True, 1, "démarrage")
    simules.add("acquittement")
    duree = tourner_jusqua(lambda: machine.etat == M.MARCHE, 60, "initialisation")
    print(f"      ✓ machine prête, les deux axes en position coupe         {duree:5.2f} s")

    for numero in range(1, cycles + 1):
        print(f"\n  Cycle {numero} / {cycles} :")
        debut_cycle = time.monotonic()

        for poste in (maitre, esclave):
            appuyer(poste, P.BRIDAGE, lambda p=poste: p.etat == P.PRET_COUPE and p.bride,
                    f"bridage {poste.nom}")

        # Les deux coupes partent ensemble : les postes sont indépendants.
        tourner_jusqua(lambda: all(machine._motif_refus(p, P.COUPE, time.monotonic()) is None
                                   for p in (maitre, esclave)),
                       DELAI_ACTION_MAX_S, "attente de l'autorisation — coupes")
        simules.update({f"coupe_{maitre.nom}", f"coupe_{esclave.nom}"})
        tourner_jusqua(lambda: maitre.etat == P.OCCUPE_COUPE and esclave.etat == P.OCCUPE_COUPE,
                       2, "départ des deux coupes")
        duree = tourner_jusqua(lambda: maitre.etat == P.PRET_COUPE and esclave.etat == P.PRET_COUPE,
                               DELAI_ACTION_MAX_S, "coupe mère + coupe fille")
        print(f"      ✓ {'coupe mère + coupe fille (ensemble)':46s} {duree:5.2f} s")
        durees.setdefault("coupe mère + coupe fille (ensemble)", []).append(duree)

        appuyer(maitre, P.POSITION, libre(maitre, P.PRET_LIGATURAGE),
                f"{maitre.nom} → position ligaturage (maître)")
        appuyer(esclave, P.POSITION, libre(esclave, P.PRET_LIGATURAGE),
                f"{esclave.nom} → position ligaturage (esclave)")

        print(f"        … ligaturage, pause de {TEMPS_LIGATURAGE_S:.1f} s")
        attendre(TEMPS_LIGATURAGE_S)

        appuyer(esclave, P.POSITION, libre(esclave, P.PRET_COUPE),
                f"{esclave.nom} → position coupe (esclave d'abord)")
        appuyer(maitre, P.POSITION, libre(maitre, P.PRET_COUPE),
                f"{maitre.nom} → position coupe (maître)")

        for poste in (maitre, esclave):
            appuyer(poste, P.BRIDAGE, lambda p=poste: p.etat == P.PRET_COUPE and not p.bride,
                    f"débridage {poste.nom}")

        faits += 1
        print(f"      cycle {numero} terminé en {time.monotonic() - debut_cycle:.1f} s")
        if numero < cycles:
            attendre(PAUSE_ENTRE_CYCLES_S)
    print(f"\n  {faits} cycle(s) complet(s), sans défaut ni refus.")
except Arret as arret:
    print(f"\n  ✗ ARRÊT : {arret}")
except KeyboardInterrupt:
    print("\n  Interrompu.")
finally:
    machine.arreter()
    materiel.fermer()
    if durees:
        print("\n  ┌─ RÉCAPITULATIF À M'ENVOYER " + "─" * 46)
        print(f"  │ {faits} cycle(s) complet(s) sur {cycles} demandé(s) — maître : {maitre.nom}")
        print("  │")
        print("  │ action                                          fois   durée moy.   min / max")
        for quoi, liste in durees.items():
            print(f"  │ {quoi:46s} {len(liste):^5d}  {sum(liste) / len(liste):6.2f} s   "
                  f"{min(liste):5.2f} / {max(liste):5.2f} s")
        print("  └" + "─" * 73)
    print("  Relais à 0, moteurs libres.\n")
