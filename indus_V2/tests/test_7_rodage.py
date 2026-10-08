# -*- coding: utf-8 -*-
"""
test_7_rodage.py — Allers-retours des DEUX axes entre leurs fins de course, en synchrone.

⚠ CE TEST FAIT TOURNER LES DEUX MOTEURS EN MÊME TEMPS. Arrêt d'urgence à portée
   de main. test_5_moteur.py validé sur les deux axes d'abord.

⚠ Ce test n'applique PAS la règle maître / esclave du programme : les deux axes
   partent ensemble. À faire SANS bois, et seulement si les deux axes peuvent se
   croiser librement à vide.

    python3 tests/test_7_rodage.py            au profil (accélération, palier, décélération)
    python3 tests/test_7_rodage.py --lent     tout à vitesse d'approche

Déroulé :
  1. AUTO-TEST DE DÉPART — pour chaque axe, l'un après l'autre : lecture des
     fins de course (en coupe ? en ligaturage ? entre les deux ?), puis mise en
     position COUPE à vitesse lente. Le sens de rotation est vérifié en route :
     si l'axe arrive sur LIGATURAGE alors qu'il vise COUPE, ou s'il ne quitte
     pas LIGATURAGE, tout s'arrête avec la correction à faire dans config.py.
  2. Après ton accord, les deux axes partent ENSEMBLE vers LIGATURAGE ; chacun
     s'arrête sur sa propre fin de course ; le script attend que LES DEUX
     soient arrivés (les courses sont différentes : l'un attend l'autre).
  3. Pause, puis les deux repartent ensemble vers COUPE ; et ainsi de suite.

Sécurités : chaque trajet est borné en pas, par axe ; arrêt des deux axes si
un moteur ne quitte pas sa fin de course de départ, s'il n'atteint pas sa
cible, ou si les deux fins de course d'un axe sont actives ensemble.
Ctrl+C arrête tout.

À la fin (ou sur Ctrl+C) : récapitulatif par axe et par sens, à m'envoyer.
"""

import sys
import time

import _commun
from _commun import cfg, confirmer, question, titre, voyant
from libs.entrees import Entrees
from libs.moteur import Axe, PortsDrivers

PAUSE_ENTRE_TRAJETS_S = 0.5
CYCLES_PAR_DEFAUT = 10

COUPE, LIGATURAGE = cfg.POSITION_COUPE, cfg.POSITION_LIGATURAGE
LENT = "--lent" in sys.argv

titre("TEST 7 — RODAGE : ALLERS-RETOURS SYNCHRONES DES DEUX AXES")
print("  ⚠ Les deux moteurs tournent en même temps, sans la règle maître / esclave.")
print("    Sans bois, axes libres de se croiser.")
reponse = question(f"Nombre d'allers-retours [{CYCLES_PAR_DEFAUT}] ?")
cycles = int(reponse) if reponse.isdigit() and int(reponse) > 0 else CYCLES_PAR_DEFAUT

materiel = _commun.ouvrir(avec_gpio=True)
drivers = PortsDrivers(materiel.drivers)
entrees = Entrees(materiel.relais, materiel.entrees)
axes = {
    cfg.POSTE_MERE: Axe(cfg.POSTE_MERE, materiel.puce, cfg.PUL_MERE, cfg.DIR_MERE, cfg.ENA_MERE, drivers),
    cfg.POSTE_FILLE: Axe(cfg.POSTE_FILLE, materiel.puce, cfg.PUL_FILLE, cfg.DIR_FILLE, cfg.ENA_FILLE, drivers),
}
mesures = {}       # (poste, cible) → [(pas au galet, pas à l'arrêt, durée jusqu'au galet)]


class Echec(Exception):
    pass


def direction(poste: str, cible: str) -> int:
    return (cfg.DIR_VERS_LIGATURAGE if cible == LIGATURAGE else cfg.DIR_VERS_COUPE)[poste]


def lire_stable() -> None:
    """Remplit l'anti-rebond : après cela, les .stable sont fiables."""
    for _ in range(12):
        entrees.rafraichir(time.monotonic())
        time.sleep(cfg.PERIODE_BOUCLE_S)


def arreter_tout() -> None:
    for axe in axes.values():
        axe.demander_arret()
    for axe in axes.values():
        axe.attendre_fin(cfg.ARRET_THREAD_MAX_S)
        axe.liberer()


def mise_en_coupe(poste: str) -> None:
    """Auto-test de départ d'un axe : où est-il, puis mise en COUPE lente en
    vérifiant le sens de rotation."""
    axe = axes[poste]
    coupe, ligaturage = entrees.capteur(poste, COUPE), entrees.capteur(poste, LIGATURAGE)
    lire_stable()
    print(f"    {poste:5s} : COUPE {voyant(coupe.stable)}  LIGATURAGE {voyant(ligaturage.stable)}  → ",
          end="", flush=True)
    if coupe.stable and ligaturage.stable:
        raise Echec(f"{poste} : les deux fins de course actives ensemble (voir test_3)")
    if coupe.stable:
        print("déjà en position COUPE")
        return
    parti_de_ligaturage = ligaturage.stable
    print("en position LIGATURAGE, retour vers COUPE…" if parti_de_ligaturage
          else "entre les deux, recherche de COUPE…", end="", flush=True)

    conseil = (f"\n      → inverser DIR_VERS_LIGATURAGE[{poste}] dans config.py "
               f"(actuellement {cfg.DIR_VERS_LIGATURAGE[poste]}), ou vérifier le câblage DIR")
    axe.preparer(direction(poste, COUPE))
    axe.lancer(cfg.MOTEUR_BUDGET_PAS[poste] + cfg.MOTEUR_MARGE_PAS, lent=True)
    arrive = False
    try:
        while axe.en_marche:
            entrees.rafraichir(time.monotonic())
            if coupe.stable and ligaturage.stable:
                raise Echec(f"{poste} : les deux fins de course actives ensemble")
            if not arrive and coupe.consecutifs >= cfg.CAPTEUR_LECTURES_ARRET:
                arrive = True
                axe.demander_arret_apres(cfg.MOTEUR_SURCOURSE_PAS)
            elif not arrive and not parti_de_ligaturage \
                    and ligaturage.consecutifs >= cfg.CAPTEUR_LECTURES_ARRET:
                raise Echec(f"{poste} : SENS INVERSÉ — l'axe est arrivé sur LIGATURAGE en visant COUPE"
                            + conseil)
            elif not arrive and parti_de_ligaturage and ligaturage.stable \
                    and axe.pas >= cfg.MOTEUR_DEGAGEMENT_MAX_PAS:
                raise Echec(f"{poste} : toujours sur LIGATURAGE après {axe.pas} pas — le moteur ne tourne "
                            "pas (puissance, LED du driver), ou il tourne dans le mauvais sens" + conseil)
            time.sleep(cfg.PERIODE_BOUCLE_S)
    finally:
        axe.demander_arret()
        axe.attendre_fin(cfg.ARRET_THREAD_MAX_S)
        axe.liberer()
    if axe.erreur is not None:
        raise Echec(f"{poste} : génération d'impulsions interrompue ({axe.erreur})")
    if not arrive:
        raise Echec(f"{poste} : position COUPE non trouvée en {axe.pas} pas — sens inversé, moteur "
                    "bloqué, ou fin de course COUPE hors service" + conseil)
    print(f" ✓ en COUPE après {axe.pas} pas, sens correct")


def trajet_synchrone(cible: str) -> dict:
    """Les deux axes vers `cible`, ensemble. Rend la main quand LES DEUX sont arrivés.
    Renvoie poste → (pas au galet, pas à l'arrêt, durée jusqu'au galet)."""
    depart = COUPE if cible == LIGATURAGE else LIGATURAGE
    entrees.rafraichir(time.monotonic())
    for poste in cfg.POSTES:
        if entrees.capteur(poste, cible).brut:
            raise Echec(f"{poste} : fin de course {cible} déjà active avant le départ")

    for poste, axe in axes.items():               # ENA et DIR des deux, puis départ groupé
        axe.preparer(direction(poste, cible))
    debut = time.monotonic()
    for poste, axe in axes.items():
        axe.lancer(cfg.MOTEUR_BUDGET_PAS[poste], LENT)

    galet = {}                                     # poste → (pas, durée)
    try:
        while any(axe.en_marche for axe in axes.values()):
            maintenant = time.monotonic()
            entrees.rafraichir(maintenant)
            for poste, axe in axes.items():
                c_cible, c_depart = entrees.capteur(poste, cible), entrees.capteur(poste, depart)
                if c_cible.stable and c_depart.stable:
                    raise Echec(f"{poste} : les deux fins de course actives ensemble")
                if poste in galet:
                    continue
                if c_cible.consecutifs >= cfg.CAPTEUR_LECTURES_ARRET:
                    galet[poste] = (axe.pas, maintenant - debut)
                    axe.demander_arret_apres(cfg.MOTEUR_SURCOURSE_PAS)
                elif axe.pas >= cfg.MOTEUR_DEGAGEMENT_MAX_PAS and c_depart.stable:
                    raise Echec(f"{poste} : fin de course {depart} toujours active après {axe.pas} pas "
                                "— le moteur ne tourne pas, ou tourne dans le mauvais sens")
            time.sleep(cfg.PERIODE_BOUCLE_S)
    finally:
        arreter_tout()

    for poste, axe in axes.items():
        if axe.erreur is not None:
            raise Echec(f"{poste} : génération d'impulsions interrompue ({axe.erreur})")
        if poste not in galet:
            raise Echec(f"{poste} : fin de course {cible} non atteinte en {axe.pas} pas "
                        f"(budget {cfg.MOTEUR_BUDGET_PAS[poste]})")
    return {poste: (galet[poste][0], axes[poste].pas, galet[poste][1]) for poste in cfg.POSTES}


def recapitulatif(faits: int) -> None:
    print("\n  ┌─ RÉCAPITULATIF À M'ENVOYER " + "─" * 46)
    print(f"  │ {faits} trajet(s) synchrone(s), mode {'LENT' if LENT else 'PROFIL'} — "
          f"{cfg.DRIVER_PAS_PAR_TOUR} pas/tr, rampes {'en S' if cfg.MOTEUR_RAMPES_EN_S else 'droites'}")
    print(f"  │ max {cfg.MOTEUR_VITESSE_MAX_SPS:.0f} pas/s, approche {cfg.MOTEUR_VITESSE_APPROCHE_SPS:.0f} "
          f"pas/s, accél. {cfg.MOTEUR_ACCEL_SPS2:.0f}, décél. {cfg.MOTEUR_DECEL_SPS2:.0f} pas/s²")
    for poste in cfg.POSTES:
        print(f"  │ {poste:5s} : course config {cfg.MOTEUR_COURSE_PAS[poste]} pas, pointe "
              f"{cfg.MOTEUR_VITESSE_POINTE_SPS[poste]:.0f} pas/s, DIR vers ligaturage = "
              f"{cfg.DIR_VERS_LIGATURAGE[poste]}")
    print("  │")
    print("  │ axe    sens              trajets  pas au galet (min / moy / max)   durée moy.")
    for (poste, sens), liste in mesures.items():
        pas = [m[0] for m in liste]
        durees = [m[2] for m in liste]
        print(f"  │ {poste:5s}  vers {sens:11s}  {len(liste):^7d}  "
              f"{min(pas):5d} / {sum(pas) / len(pas):7.1f} / {max(pas):5d}        "
              f"{sum(durees) / len(durees):5.2f} s")
    print("  └" + "─" * 73)


faits = 0
try:
    # ── 1. Auto-test de départ : état, mise en COUPE, sens de rotation ─────
    esclave = cfg.POSTE_FILLE if cfg.MOTEUR_MAITRE == cfg.POSTE_MERE else cfg.POSTE_MERE
    print("\n  Auto-test de départ (lent, un axe après l'autre, l'esclave d'abord) :")
    for poste in (esclave, cfg.MOTEUR_MAITRE):
        mise_en_coupe(poste)
    print("  Les deux axes sont en position COUPE.")

    if not confirmer(f"Lancer {cycles} allers-retours synchrones ({'LENT' if LENT else 'PROFIL'}) ?"):
        raise SystemExit("  Non lancé.")

    # ── 2. Allers-retours synchrones ───────────────────────────────────────
    print("\n   n°  sens             mère : galet / arrêt / durée     fille : galet / arrêt / durée")
    cible = LIGATURAGE
    for numero in range(1, 2 * cycles + 1):
        resultat = trajet_synchrone(cible)
        faits += 1
        for poste, valeurs in resultat.items():
            mesures.setdefault((poste, cible), []).append(valeurs)
        m, f = resultat[cfg.POSTE_MERE], resultat[cfg.POSTE_FILLE]
        print(f"  {numero:4d}  vers {cible:11s}  {m[0]:5d} / {m[1]:5d} / {m[2]:5.2f} s"
              f"          {f[0]:5d} / {f[1]:5d} / {f[2]:5.2f} s")
        cible = COUPE if cible == LIGATURAGE else LIGATURAGE
        time.sleep(PAUSE_ENTRE_TRAJETS_S)
    print(f"\n  Rodage terminé : {cycles} allers-retours sans défaut.")
except Echec as echec:
    print(f"\n  ✗ ARRÊT : {echec}")
except KeyboardInterrupt:
    print("\n  Interrompu.")
finally:
    for axe in axes.values():
        axe.demander_arret()
    for axe in axes.values():
        axe.attendre_fin(cfg.ARRET_THREAD_MAX_S)
    materiel.fermer()
    if mesures:
        recapitulatif(faits)
    print("  Moteurs arrêtés et libres, relais à 0.\n")
