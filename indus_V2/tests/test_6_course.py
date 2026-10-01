# -*- coding: utf-8 -*-
"""
test_6_course.py — Mesure de la course COUPE ↔ LIGATURAGE, pour MOTEUR_COURSE_DEGRES.

⚠ CE TEST FAIT TOURNER UN MOTEUR. Arrêt d'urgence à portée de main.
   Faire d'abord test_5_moteur.py : sens et arrêt sur fin de course validés.

    python3 tests/test_6_course.py

Déroulé, à vitesse d'approche uniquement :
  1. si l'axe n'est pas en position COUPE, recherche lente vers COUPE ;
  2. COUPE → LIGATURAGE en comptant les pas jusqu'au galet ;
  3. LIGATURAGE → COUPE en comptant les pas jusqu'au galet ;
  4. valeur proposée pour MOTEUR_COURSE_DEGRES (avec la MOTEUR_REDUCTION actuelle).

Le budget de ce test est volontairement large (BUDGET_TEST_FACTEUR × le budget
normal), puisque la course réelle est justement inconnue. Surveiller l'axe.
"""

import _commun
from _commun import attendre_entree, cfg, deplacer, question, titre
from libs.entrees import Entrees
from libs.moteur import Axe, PortsDrivers

BUDGET_TEST_FACTEUR = 1.5   # budget de mesure = 1,5 × MOTEUR_BUDGET_PAS

titre("TEST 6 — MESURE DE LA COURSE")
choix = question("Axe à mesurer : m = mère, f = fille ?")
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
budget = round(cfg.MOTEUR_BUDGET_PAS * BUDGET_TEST_FACTEUR)

try:
    print(f"\n  Budget de mesure : {budget} pas "
          f"({budget / cfg.PAS_PAR_DEGRE:.0f}° d'axe avec la réduction {cfg.MOTEUR_REDUCTION}).")
    attendre_entree("Entrée pour lancer : mise en position COUPE.")
    pas_capteur, _ = deplacer(axe, entrees, poste, cfg.POSITION_COUPE, lent=True, budget=budget)
    if pas_capteur is None:
        raise SystemExit("  ✗ position COUPE non trouvée — voir test_5_moteur.py")

    mesures = {}
    for cible in (cfg.POSITION_LIGATURAGE, cfg.POSITION_COUPE):
        attendre_entree(f"Entrée pour mesurer la course vers {cible.upper()}.")
        pas_capteur, total = deplacer(axe, entrees, poste, cible, lent=True, budget=budget)
        if pas_capteur is None:
            raise SystemExit(f"  ✗ fin de course {cible} non atteinte en {total} pas")
        mesures[cible] = pas_capteur
        print(f"  ✓ vers {cible:11s} : galet atteint après {pas_capteur} pas")

    moyenne = sum(mesures.values()) / len(mesures)
    degres_moteur = moyenne * 360.0 / cfg.DRIVER_PAS_PAR_TOUR
    print("\n  Résultat :")
    print(f"    course moyenne    : {moyenne:.0f} pas = {degres_moteur:.1f}° d'arbre moteur")
    print(f"    avec MOTEUR_REDUCTION = {cfg.MOTEUR_REDUCTION} → {moyenne / cfg.PAS_PAR_DEGRE:.1f}° d'axe")
    print(f"\n    → dans config.py : MOTEUR_COURSE_DEGRES = {moyenne / cfg.PAS_PAR_DEGRE:.1f}")
    print(f"      (actuellement {cfg.MOTEUR_COURSE_DEGRES}, soit {cfg.MOTEUR_COURSE_PAS} pas)")
    ecart = abs(mesures[cfg.POSITION_LIGATURAGE] - mesures[cfg.POSITION_COUPE])
    if ecart > cfg.MOTEUR_SURCOURSE_PAS + 10:
        print(f"\n    ⚠ aller et retour diffèrent de {ecart} pas : perte de pas, jeu mécanique,")
        print("      ou galet à course morte importante. À comprendre avant de continuer.")
    print()
except KeyboardInterrupt:
    print("\n  Interrompu.")
finally:
    axe.demander_arret()
    axe.attendre_fin(cfg.ARRET_THREAD_MAX_S)
    materiel.fermer()
    print("  Moteur arrêté et libre, relais à 0.\n")
