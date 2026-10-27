# -*- coding: utf-8 -*-
"""
test_6_course.py — Mesure de la plage de rotation butée à butée, pour PLAGE_NOMINALE_DEG.

⚠ CE TEST FAIT TOURNER UN MOTEUR. Arrêt d'urgence à portée de main, mandrin
   vide. Faire d'abord test_5_moteur.py : sens et arrêt sur butée validés.

    python3 tests/test_6_course.py

Le test lance plusieurs fois L'INITIALISATION RÉELLE du poste (le code de
main.py) : passe rapide, recul, passe lente de chaque côté, puis centrage.
À chaque fois il relève :
  - la plage mesurée par les passes lentes (celle que le programme retient) ;
  - l'écart entre passe rapide et passe lente sur chaque butée (retard d'arrêt
    à grande vitesse, élasticité, jeu) ;
  - la durée de l'initialisation.
Puis il propose PLAGE_NOMINALE_DEG.

La tolérance de plage (D9) est élargie pour ce test : la plage est justement
inconnue. Le budget de la passe rapide aussi (BUDGET_TEST_FACTEUR). Surveiller
le mandrin.
"""

import _commun
from _commun import cfg, question, titre
from libs.poste import Defaut

BUDGET_TEST_FACTEUR = 1.5      # budget de la passe rapide = 1,5 × le budget normal
MESURES_PAR_DEFAUT = 3
H, A = cfg.SENS_HORAIRE, cfg.SENS_ANTIHORAIRE

titre("TEST 6 — MESURE DE LA PLAGE DE ROTATION")
choix = question("Poste à mesurer : m = mère, f = fille ?")
nom = cfg.POSTE_MERE if choix == "m" else cfg.POSTE_FILLE if choix == "f" else None
if nom is None:
    raise SystemExit("  choix invalide")
reponse = question(f"Nombre de mesures [{MESURES_PAR_DEFAUT}] ?")
mesures_demandees = int(reponse) if reponse.isdigit() and int(reponse) > 0 else MESURES_PAR_DEFAUT

# Plage inconnue : tolérance et budget élargis pour ce test seulement.
cfg.PLAGE_TOLERANCE_PAS = round(0.9 * cfg.PLAGE_NOMINALE_PAS[nom])
cfg.BUDGET_RECHERCHE_RAPIDE_PAS[nom] = round(cfg.BUDGET_RECHERCHE_RAPIDE_PAS[nom] * BUDGET_TEST_FACTEUR)

materiel = _commun.ouvrir(avec_gpio=True)
entrees, postes, buzzer = _commun.construire_postes(materiel, (nom,))
poste = postes[nom]

resultats = []          # (plage en pas, écart rapide/lente A, écart H, durée)
try:
    print(f"\n  Budget de la passe rapide : {cfg.BUDGET_RECHERCHE_RAPIDE_PAS[nom]} pas "
          f"({cfg.BUDGET_RECHERCHE_RAPIDE_PAS[nom] / cfg.PAS_PAR_DEGRE:.0f}°).")
    _commun.attendre_entree("Entrée pour lancer les mesures.")
    for numero in range(1, mesures_demandees + 1):
        duree = _commun.initialiser(entrees, postes, buzzer)
        ecarts = {}
        for sens in (A, H):
            rapide = poste.detection_rapide.get(sens)
            lente = poste.repere_lent[sens]
            signe = 1 if sens == H else -1
            ecarts[sens] = None if rapide is None else signe * (rapide - lente)
        resultats.append((poste.plage, ecarts[A], ecarts[H], duree))

        def texte(ecart):
            return "   départ sur la butée" if ecart is None else f"{ecart / cfg.PAS_PAR_DEGRE:+6.2f}°"
        print(f"  ✓ mesure {numero} : plage {poste.plage} pas = {poste.degres(poste.plage)}, "
              f"écart rapide/lente  A {texte(ecarts[A])}  H {texte(ecarts[H])}, {duree:.1f} s")

    plages = [r[0] for r in resultats]
    moyenne = sum(plages) / len(plages)
    print("\n  Résultat :")
    print(f"    plage : min {min(plages)} / moy {moyenne:.0f} / max {max(plages)} pas "
          f"(dispersion {(max(plages) - min(plages)) / cfg.PAS_PAR_DEGRE:.2f}°)")
    print(f"\n    → dans config.py : PLAGE_NOMINALE_DEG[{nom}] = {moyenne / cfg.PAS_PAR_DEGRE:.1f}")
    print(f"      (actuellement {cfg.PLAGE_NOMINALE_DEG[nom]:.1f}°)")
    if max(plages) - min(plages) > cfg.ECART_RECALAGE_MAX_PAS:
        print("\n    ⚠ les mesures diffèrent de plus de ECART_RECALAGE_MAX_DEG : perte de pas, jeu")
        print("      mécanique ou galet à course morte importante. À comprendre avant de continuer.")
    print()
except Defaut as defaut:
    print(f"\n  ✗ DÉFAUT {defaut.code} : {defaut.detail}")
except TimeoutError as erreur:
    print(f"\n  ✗ {erreur}")
except KeyboardInterrupt:
    print("\n  Interrompu.")
finally:
    _commun.arreter_postes(postes)
    materiel.fermer()
    print("  Moteur arrêté et libre, relais à 0.\n")
