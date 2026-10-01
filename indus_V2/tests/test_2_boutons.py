# -*- coding: utf-8 -*-
"""
test_2_boutons.py — Correspondance bouton physique ↔ bit, anti-rebond, fronts.

Aucune sortie activée. Affichage en direct, Ctrl+C pour le bilan.

    python3 tests/test_2_boutons.py

Procédure : appuyer UNE fois sur chaque bouton, dans l'ordre de l'affichage.
  - Le bon voyant doit s'allumer, et le compteur d'appuis augmenter de 1.
  - Si c'est un autre voyant qui s'allume : échanger les valeurs BTN_* dans
    config.py. Les octets bruts, affichés à droite, montrent quel bit bouge.
  - Un appui maintenu ne doit compter qu'UN appui (front unique).
"""

import time

import _commun
from _commun import bits, cfg, titre, voyant
from libs.entrees import NOMS_BOUTONS, Entrees

ABREGES = {"bridage_mere": "BRI.M", "coupe_mere": "COU.M", "position_mere": "POS.M",
           "bridage_fille": "BRI.F", "coupe_fille": "COU.F", "position_fille": "POS.F",
           "acquittement": "ACQ"}

titre("TEST 2 — BOUTONS")
print("  Appuyer une fois sur chaque bouton. Ctrl+C pour le bilan.\n")
print("  " + "  ".join(f"{ABREGES[n]:>5}" for n in NOMS_BOUTONS) + "   0x24 B      0x26 B")

materiel = _commun.ouvrir(avec_gpio=False)
entrees = Entrees(materiel.relais, materiel.entrees)
appuis = {nom: 0 for nom in NOMS_BOUTONS}
try:
    while True:
        entrees.rafraichir(time.monotonic())
        ligne = []
        for nom in NOMS_BOUTONS:
            if entrees.appui(nom):
                appuis[nom] += 1
            ligne.append(f"{voyant(entrees.boutons[nom].stable)}{appuis[nom]:>3}")
        print("\r  " + "  ".join(f"{c:>5}" for c in ligne)
              + f"   {bits(entrees.octets['0x24_B'])}   {bits(entrees.octets['0x26_B'])}",
              end="", flush=True)
        time.sleep(cfg.PERIODE_BOUCLE_S)
except KeyboardInterrupt:
    print("\n\n  Bilan :")
    for nom in NOMS_BOUTONS:
        etat = f"✓ {appuis[nom]} appui(s)" if appuis[nom] else "✗ jamais vu"
        print(f"    {nom:15s} {etat}")
    print()
finally:
    materiel.fermer()
