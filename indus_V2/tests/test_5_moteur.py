# -*- coding: utf-8 -*-
"""
test_5_moteur.py — Un axe : bon moteur, bon sens, arrêt sur fin de course, profil.

⚠ CE TEST FAIT TOURNER UN MOTEUR. Arrêt d'urgence à portée de main.
   Faire d'abord test_3_capteurs.py : l'arrêt dépend des fins de course.

    python3 tests/test_5_moteur.py

Étapes, toutes confirmées au clavier :
  1. SENS — quelques degrés à vitesse lente, sans fin de course.
       Vérifie que c'est LE BON AXE qui tourne (sinon PUL / DIR / ENA mal
       affectés : DIR_MERE, DIR_FILLE, ENA_*, PUL_* dans config.py) et qu'il
       part DU BON CÔTÉ (sinon échanger DIR_VERS_COUPE / DIR_VERS_LIGATURAGE).
  2. COURSE LENTE — jusqu'à la fin de course opposée, à vitesse d'approche.
  3. COURSE AU PROFIL — aller-retour avec accélération, palier, décélération.
       Pour régler MOTEUR_VITESSE_MAX_SPS / ACCEL / DECEL : monter
       progressivement jusqu'au décrochage (bruit, perte de pas), puis
       redescendre d'environ 30 %.

Tout mouvement est borné par MOTEUR_BUDGET_PAS. Ctrl+C arrête le moteur.
"""

import time

import _commun
from _commun import attendre_entree, cfg, confirmer, deplacer, pas_a_vide, question, titre
from libs.entrees import Entrees
from libs.moteur import Axe, PortsDrivers

DEGRES_TEST_SENS = 5.0     # amplitude de l'étape 1, degrés d'axe

titre("TEST 5 — MOTEUR")
choix = question("Axe à tester : m = mère, f = fille ?")
poste = cfg.POSTE_MERE if choix == "m" else cfg.POSTE_FILLE if choix == "f" else None
if poste is None:
    raise SystemExit("  choix invalide")

materiel = _commun.ouvrir(avec_gpio=True)
drivers = PortsDrivers(materiel.drivers)
entrees = Entrees(materiel.relais, materiel.entrees)
if poste == cfg.POSTE_MERE:
    axe = Axe(poste, materiel.puce, cfg.PUL_MERE, cfg.DIR_MERE, cfg.ENA_MERE, drivers)
else:
    axe = Axe(poste, materiel.puce, cfg.PUL_FILLE, cfg.DIR_FILLE, cfg.ENA_FILLE, drivers)


def position_lue() -> str | None:
    for _ in range(10):                       # remplit l'anti-rebond
        entrees.rafraichir(time.monotonic())
        time.sleep(cfg.PERIODE_BOUCLE_S)
    coupe = entrees.capteur(poste, cfg.POSITION_COUPE).stable
    lig = entrees.capteur(poste, cfg.POSITION_LIGATURAGE).stable
    if coupe and lig:
        raise SystemExit("  ⚠ les deux fins de course sont actives (défaut D2) — voir test_3")
    return cfg.POSITION_COUPE if coupe else cfg.POSITION_LIGATURAGE if lig else None


def opposee(position: str) -> str:
    return cfg.POSITION_LIGATURAGE if position == cfg.POSITION_COUPE else cfg.POSITION_COUPE


try:
    depart = position_lue()
    print(f"\n  Axe {poste} — position lue : {depart or 'aucune fin de course active'}")

    # ── 1. SENS ────────────────────────────────────────────────────────────
    vers = opposee(depart) if depart else cfg.POSITION_LIGATURAGE
    nombre = round(cfg.PAS_PAR_DEGRE * DEGRES_TEST_SENS)
    direction = cfg.DIR_VERS_LIGATURAGE if vers == cfg.POSITION_LIGATURAGE else cfg.DIR_VERS_COUPE
    print(f"\n  ÉTAPE 1 — {nombre} pas ({DEGRES_TEST_SENS:.0f}°) lents, vers la position {vers.upper()}.")
    attendre_entree("Entrée pour lancer.")
    pas_a_vide(axe, direction, nombre)
    if not confirmer(f"L'axe {poste.upper()} a-t-il tourné (et pas l'autre) ?"):
        print("  → vérifier DIR_MERE / DIR_FILLE, ENA_*, PUL_* dans config.py,")
        print("    l'alimentation de puissance du driver et sa LED d'alarme.")
        raise SystemExit(1)
    if not confirmer(f"Est-il parti vers la position {vers.upper()} ?"):
        print("  → échanger DIR_VERS_COUPE et DIR_VERS_LIGATURAGE dans config.py.")
        pas_a_vide(axe, cfg.DIR_VERS_COUPE if vers == cfg.POSITION_LIGATURAGE else cfg.DIR_VERS_LIGATURAGE,
                   nombre)
        raise SystemExit(1)

    # ── 2. COURSE LENTE ────────────────────────────────────────────────────
    cible = vers
    print(f"\n  ÉTAPE 2 — course LENTE jusqu'à la fin de course {cible.upper()} "
          f"(budget {cfg.MOTEUR_BUDGET_PAS} pas).")
    attendre_entree("Entrée pour lancer.")
    pas_capteur, total = deplacer(axe, entrees, poste, cible, lent=True, budget=cfg.MOTEUR_BUDGET_PAS)
    if pas_capteur is None:
        print(f"  ✗ fin de course {cible} NON atteinte en {total} pas (ce serait un défaut D1).")
        raise SystemExit(1)
    print(f"  ✓ fin de course {cible} atteinte après {pas_capteur} pas, arrêt à {total} pas.")

    # ── 3. COURSE AU PROFIL ────────────────────────────────────────────────
    print(f"\n  ÉTAPE 3 — aller-retour au PROFIL : {cfg.MOTEUR_VITESSE_MAX_SPS:.0f} pas/s max, "
          f"rampes {cfg.MOTEUR_ACCEL_PAS} / {cfg.MOTEUR_DECEL_PAS} pas, approche "
          f"{cfg.MOTEUR_VITESSE_APPROCHE_SPS:.0f} pas/s.")
    while confirmer("Lancer un aller-retour ?"):
        for cible in (opposee(cible), opposee(opposee(cible))):
            pas_capteur, total = deplacer(axe, entrees, poste, cible, lent=False,
                                          budget=cfg.MOTEUR_BUDGET_PAS)
            if pas_capteur is None:
                print(f"  ✗ fin de course {cible} NON atteinte en {total} pas (défaut D1).")
                raise SystemExit(1)
            print(f"  ✓ {cible:11s} : capteur à {pas_capteur} pas, arrêt à {total} pas")
except KeyboardInterrupt:
    print("\n  Interrompu.")
finally:
    axe.demander_arret()
    axe.attendre_fin(cfg.ARRET_THREAD_MAX_S)
    materiel.fermer()
    print("  Moteur arrêté et libre, relais à 0.\n")
