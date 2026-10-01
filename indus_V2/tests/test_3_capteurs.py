# -*- coding: utf-8 -*-
"""
test_3_capteurs.py — Correspondance et polarité des 4 fins de course, repli au débranchement.

Aucune sortie activée. Les moteurs sont LIBRES (ENA = 1) : on peut amener les
axes à la main, si la mécanique le permet.

    python3 tests/test_3_capteurs.py

Procédure, pour chaque axe :
  1. Axe hors des deux positions → les deux voyants de l'axe éteints « ·· ».
  2. Axe en position COUPE        → seul le voyant COUPE de cet axe allumé.
  3. Axe en position LIGATURAGE   → seul le voyant LIGATURAGE de cet axe allumé.
  4. Galet actionné, DÉBRANCHER le connecteur → le voyant doit S'ÉTEINDRE.
     C'est le repli sûr voulu (contact NO, actif bas) : un fil coupé se lit
     « pas en position », jamais comme une fausse arrivée.

Si un voyant s'allume quand le galet est LIBRE et s'éteint quand il est
actionné : polarité inversée → CAPTEURS_ACTIFS_BAS, ou câblage NF au lieu de NO.
Si c'est le voyant d'un autre capteur qui réagit : échanger les CAP_* dans config.py.
"""

import time

import _commun
from _commun import bits, cfg, titre, voyant
from libs.entrees import Entrees

CAPTEURS = ((cfg.POSTE_MERE, cfg.POSITION_COUPE), (cfg.POSTE_MERE, cfg.POSITION_LIGATURAGE),
            (cfg.POSTE_FILLE, cfg.POSITION_COUPE), (cfg.POSTE_FILLE, cfg.POSITION_LIGATURAGE))

titre("TEST 3 — FINS DE COURSE")
print(f"  Polarité configurée : {'actif BAS (contact NO)' if cfg.CAPTEURS_ACTIFS_BAS else 'actif HAUT'}")
print("  Ctrl+C pour le bilan.\n")
print("  MÈRE coupe  MÈRE lig.  FILLE coupe  FILLE lig.   0x26 A (bits 7..4 = capteurs)")

materiel = _commun.ouvrir(avec_gpio=False)
entrees = Entrees(materiel.relais, materiel.entrees)
vus = {cle: False for cle in CAPTEURS}
incoherences = 0
try:
    while True:
        entrees.rafraichir(time.monotonic())
        alerte = ""
        for poste in cfg.POSTES:
            if (entrees.capteur(poste, cfg.POSITION_COUPE).stable
                    and entrees.capteur(poste, cfg.POSITION_LIGATURAGE).stable):
                alerte = f"  ⚠ {poste} : LES DEUX actifs (défaut D2)"
                incoherences += 1
        for cle in CAPTEURS:
            vus[cle] |= entrees.capteurs[cle].stable
        print("\r  " + "   ".join(f"   {voyant(entrees.capteurs[cle].stable)}    " for cle in CAPTEURS)
              + f"  {bits(entrees.octets['0x26_A'])}{alerte:40s}", end="", flush=True)
        time.sleep(cfg.PERIODE_BOUCLE_S)
except KeyboardInterrupt:
    print("\n\n  Bilan :")
    for (poste, position), vu in vus.items():
        print(f"    {poste:6s} {position:11s} {'✓ vu actif' if vu else '✗ jamais vu actif'}")
    if incoherences:
        print("    ⚠ deux capteurs d'un même axe ont été vus actifs ensemble")
    print()
finally:
    materiel.fermer()
