# -*- coding: utf-8 -*-
"""
test_2_boutons.py — Aperçu en direct des 7 boutons.

Lecture seule : aucun relais, aucun ENA n'est écrit.

    python3 tests/test_2_boutons.py                 APERÇU (par défaut)
    python3 tests/test_2_boutons.py --attribution   refaire la correspondance

APERÇU : chaque bouton a son voyant et son compteur d'appuis, selon config.py
(correspondance relevée sur machine le 2026-10-08). Un appui = le bon voyant
s'allume et son compteur augmente de 1. Un appui maintenu ne compte qu'UN
appui. Ctrl+C pour le bilan.

ATTRIBUTION : à refaire seulement si le câblage change. Le script nomme une
fonction, tu appuies sur le bouton voulu, il affiche les lignes BTN_* à
recopier dans config.py.
"""

import sys
import time

import _commun
from _commun import bits, cfg, titre, voyant
from libs.entrees import NOMS_BOUTONS, Entrees, Filtre
from libs.materiel import PORT_B

ABREGES = {"bridage_mere": "BRI.M", "coupe_mere": "COU.M", "position_mere": "POS.M",
           "bridage_fille": "BRI.F", "coupe_fille": "COU.F", "position_fille": "POS.F",
           "acquittement": "ACQ"}
LIBELLES = {"bridage_mere": "BRIDAGE MÈRE", "coupe_mere": "COUPE MÈRE",
            "position_mere": "POSITION MÈRE", "bridage_fille": "BRIDAGE FILLE",
            "coupe_fille": "COUPE FILLE", "position_fille": "POSITION FILLE",
            "acquittement": "ACQUITTEMENT"}
CONSTANTES = {nom: "BTN_" + nom.upper() for nom in NOMS_BOUTONS}


def mode_direct(materiel) -> None:
    print("  Appuyer une fois sur chaque bouton. Ctrl+C pour le bilan.\n")
    print("  " + "  ".join(f"{ABREGES[n]:>5}" for n in NOMS_BOUTONS) + "   0x24 B      0x26 B")
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


def mode_attribution(materiel) -> None:
    # Un filtre par bit brut des deux ports B : (port, bit) → Filtre.
    filtres = {(port, bit): Filtre(cfg.ANTI_REBOND_BOUTON_S)
               for port in ("0x24", "0x26") for bit in range(8)}

    def lire() -> list:
        """Rafraîchit tous les filtres ; renvoie les (port, bit) qui viennent d'être appuyés."""
        octets = {"0x24": materiel.relais.lire_port(PORT_B),
                  "0x26": materiel.entrees.lire_ports()[1]}
        maintenant = time.monotonic()
        fronts = []
        for (port, bit), filtre in filtres.items():
            niveau_haut = bool(octets[port] & (1 << bit))
            filtre.maj(not niveau_haut if cfg.BOUTONS_ACTIFS_BAS else niveau_haut, maintenant)
            if filtre.front:
                fronts.append((port, bit))
        return fronts

    print("  Pour chaque fonction annoncée, appuyer sur le bouton voulu.")
    print("  Ctrl+C pour abandonner.\n")
    attribution: dict = {}
    for nom in NOMS_BOUTONS:
        print(f"  → Appuie sur le bouton {LIBELLES[nom]:15s} … ", end="", flush=True)
        while True:
            fronts = lire()
            time.sleep(cfg.PERIODE_BOUCLE_S)
            if not fronts:
                continue
            if len(fronts) > 1:
                print("\n    ⚠ plusieurs bits en même temps "
                      + ", ".join(f"{p} GPB{b}" for p, b in fronts)
                      + " — recommence … ", end="", flush=True)
                continue
            deja = [n for n, pb in attribution.items() if pb == fronts[0]]
            if deja:
                print(f"\n    ⚠ ce bouton est déjà attribué à {LIBELLES[deja[0]]} "
                      "— appuie sur un autre … ", end="", flush=True)
                continue
            attribution[nom] = fronts[0]
            print(f"{fronts[0][0]} GPB{fronts[0][1]}")
            break

    print("\n  À recopier dans config.py :\n")
    for nom in NOMS_BOUTONS:
        port, bit = attribution[nom]
        print(f"    {CONSTANTES[nom]:20s} = {bit}    # {port} GPB{bit}")

    # Le programme attend les 6 boutons d'action sur le 0x24 et ACQUITTEMENT sur le 0x26.
    hors_port = [nom for nom in NOMS_BOUTONS
                 if attribution[nom][0] != ("0x26" if nom == "acquittement" else "0x24")]
    if hors_port:
        print("\n  ⚠ Câblage différent de ce que le programme attend (6 boutons d'action")
        print("    sur le 0x24 port B, ACQUITTEMENT sur le 0x26 port B) :")
        for nom in hors_port:
            print(f"      {LIBELLES[nom]} est sur le {attribution[nom][0]}")
        print("    → me le signaler : il faut adapter libs/entrees.py, pas seulement config.py.")
    print()


titre("TEST 2 — BOUTONS")
materiel = _commun.ouvrir_lecture_seule()
try:
    if "--attribution" in sys.argv:
        mode_attribution(materiel)
    else:
        mode_direct(materiel)
except KeyboardInterrupt:
    print("\n  Abandonné.\n")
finally:
    materiel.fermer()
