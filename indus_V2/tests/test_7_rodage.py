# -*- coding: utf-8 -*-
"""
test_7_rodage.py — Allers-retours des DEUX axes entre leurs fins de course, en synchrone.

⚠ CE TEST FAIT TOURNER LES DEUX MOTEURS EN MÊME TEMPS. Arrêt d'urgence à portée
   de main. test_5_moteur.py validé sur les deux axes d'abord, et config.py à
   jour (DIR_VERS_COUPE / DIR_VERS_LIGATURAGE, MOTEUR_COURSE_DEGRES).

⚠ Ce test n'applique PAS la règle maître / esclave du programme : les deux axes
   partent ensemble. À faire SANS bois, et seulement si les deux axes peuvent se
   croiser librement à vide.

    python3 tests/test_7_rodage.py            au profil (accélération, palier, décélération)
    python3 tests/test_7_rodage.py --lent     tout à vitesse d'approche

Déroulé :
  1. mise en position COUPE des deux axes, l'un après l'autre, lentement ;
  2. les deux axes partent ENSEMBLE vers LIGATURAGE ; chacun s'arrête sur sa
     propre fin de course ; le script attend que LES DEUX soient arrivés ;
  3. pause, puis les deux repartent ensemble vers COUPE ; et ainsi de suite.

Sécurités : chaque trajet est borné en pas ; arrêt des deux axes si un moteur
ne quitte pas sa fin de course de départ, s'il n'atteint pas sa cible, ou si
les deux fins de course d'un axe sont actives ensemble. Ctrl+C arrête tout.

À la fin (ou sur Ctrl+C) : récapitulatif par axe et par sens, à m'envoyer.
"""

import sys
import time

import _commun
from _commun import cfg, confirmer, deplacer, question, titre
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


def trajet_synchrone(cible: str) -> dict:
    """Les deux axes vers `cible`, ensemble. Rend la main quand LES DEUX sont arrivés.
    Renvoie poste → (pas au galet, pas à l'arrêt, durée jusqu'au galet)."""
    depart = COUPE if cible == LIGATURAGE else LIGATURAGE
    direction = cfg.DIR_VERS_LIGATURAGE if cible == LIGATURAGE else cfg.DIR_VERS_COUPE
    entrees.rafraichir(time.monotonic())
    for poste in cfg.POSTES:
        if entrees.capteur(poste, cible).brut:
            raise Echec(f"{poste} : fin de course {cible} déjà active avant le départ")

    for axe in axes.values():                     # ENA et DIR des deux, puis départ groupé
        axe.preparer(direction)
    debut = time.monotonic()
    for axe in axes.values():
        axe.lancer(cfg.MOTEUR_BUDGET_PAS, LENT)

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
        for axe in axes.values():
            axe.demander_arret()
        for axe in axes.values():
            axe.attendre_fin(cfg.ARRET_THREAD_MAX_S)
            axe.liberer()

    for poste, axe in axes.items():
        if axe.erreur is not None:
            raise Echec(f"{poste} : génération d'impulsions interrompue ({axe.erreur})")
        if poste not in galet:
            raise Echec(f"{poste} : fin de course {cible} non atteinte en {axe.pas} pas")
    return {poste: (galet[poste][0], axes[poste].pas, galet[poste][1]) for poste in cfg.POSTES}


def recapitulatif(faits: int) -> None:
    print("\n  ┌─ RÉCAPITULATIF À M'ENVOYER " + "─" * 46)
    print(f"  │ {faits} trajet(s) synchrone(s), mode {'LENT' if LENT else 'PROFIL'} — "
          f"{cfg.DRIVER_PAS_PAR_TOUR} pas/tr, rampes {'en S' if cfg.MOTEUR_RAMPES_EN_S else 'droites'}")
    print(f"  │ max {cfg.MOTEUR_VITESSE_MAX_SPS:.0f} pas/s, approche {cfg.MOTEUR_VITESSE_APPROCHE_SPS:.0f} "
          f"pas/s, accél. {cfg.MOTEUR_ACCEL_SPS2:.0f}, décél. {cfg.MOTEUR_DECEL_SPS2:.0f} pas/s², "
          f"course config {cfg.MOTEUR_COURSE_PAS} pas")
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
    # ── 1. Mise en position COUPE, un axe après l'autre, lentement ─────────
    esclave = cfg.POSTE_FILLE if cfg.MOTEUR_MAITRE == cfg.POSTE_MERE else cfg.POSTE_MERE
    print("\n  Mise en position COUPE des deux axes (lent, l'esclave d'abord)…")
    for poste in (esclave, cfg.MOTEUR_MAITRE):
        pas_capteur, total = deplacer(axes[poste], entrees, poste, COUPE, lent=True,
                                      budget=cfg.MOTEUR_BUDGET_PAS + cfg.MOTEUR_MARGE_PAS)
        if pas_capteur is None:
            raise Echec(f"{poste} : position COUPE non trouvée en {total} pas")
        print(f"    ✓ {poste} en position COUPE")

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
