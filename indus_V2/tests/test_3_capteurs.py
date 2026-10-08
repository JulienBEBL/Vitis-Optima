# -*- coding: utf-8 -*-
"""
test_3_capteurs.py — Les fins de course : laquelle est laquelle, et dans quel sens.

Lecture seule : aucun relais, aucun ENA n'est écrit.

    python3 tests/test_3_capteurs.py            mode ATTRIBUTION (par défaut)
    python3 tests/test_3_capteurs.py --direct   bits bruts en direct

Mode ATTRIBUTION : le script nomme une fin de course (« MÈRE — position COUPE »…),
tu actionnes à la main le galet correspondant puis tu le relâches. Il note sur
quel bit ça arrive et dans quel sens le bit bascule. À la fin il affiche les
lignes CAP_* à recopier dans config.py. Il écoute tous les bits des ports
d'entrée, quelle que soit la config actuelle. Ctrl+C pour abandonner.

  Rappel : « position COUPE » et « position LIGATURAGE » sont les deux bouts
  de course de chaque axe (ton min et ton max). À toi de dire lequel est lequel.

Mode DIRECT : les 8 bits bruts de chaque port et la liste de ceux qui ont
bougé. Sert aussi au test de débranchement : galet actionné, débrancher le
connecteur → le bit doit revenir à 1 (repli sûr du contact NO).
"""

import sys
import time

import _commun
from _commun import bits, titre

PORTS = ("0x26 A", "0x26 B", "0x24 B")
PERIODE_S = 0.01
LECTURES_STABLES = 5      # un changement est retenu après 5 lectures identiques (50 ms)

CAPTEURS = (("CAP_MERE_COUPE", "MÈRE  — position COUPE"),
            ("CAP_MERE_LIGATURAGE", "MÈRE  — position LIGATURAGE"),
            ("CAP_FILLE_COUPE", "FILLE — position COUPE"),
            ("CAP_FILLE_LIGATURAGE", "FILLE — position LIGATURAGE"))

titre("TEST 3 — FINS DE COURSE")
materiel = _commun.ouvrir_lecture_seule()


def lire() -> dict:
    a, b = materiel.entrees.lire_ports()
    return {"0x26 A": a, "0x26 B": b, "0x24 B": materiel.relais.lire_port(1)}


def lire_stable() -> dict:
    """Attend LECTURES_STABLES lectures identiques de suite et les renvoie."""
    precedent, identiques = lire(), 0
    while identiques < LECTURES_STABLES:
        time.sleep(PERIODE_S)
        octets = lire()
        identiques = identiques + 1 if octets == precedent else 0
        precedent = octets
    return precedent


def differences(avant: dict, apres: dict) -> list:
    return [(port, bit) for port in PORTS for bit in range(8)
            if (avant[port] ^ apres[port]) & (1 << bit)]


def mode_attribution() -> None:
    print("  Tous les galets LIBRES pour commencer. Pour chaque fin de course")
    print("  annoncée : actionner le galet à la main, puis le relâcher.")
    print("  Ctrl+C pour abandonner.\n")
    repos = lire_stable()
    print(f"  Au repos : 0x26 A = {bits(repos['0x26 A'])}   0x26 B = {bits(repos['0x26 B'])}\n")

    attribution = {}          # constante → (port, bit, niveau galet actionné)
    for constante, libelle in CAPTEURS:
        print(f"  → Actionne le galet {libelle:28s} … ", end="", flush=True)
        while True:
            octets = lire_stable()
            diff = differences(repos, octets)
            if not diff:
                continue
            if len(diff) > 1:
                print("\n    ⚠ plusieurs bits à la fois : "
                      + ", ".join(f"{p} bit {b}" for p, b in diff)
                      + " — relâche tout et recommence … ", end="", flush=True)
            elif any(pb == diff[0] for pb in ((a[0], a[1]) for a in attribution.values())):
                print("\n    ⚠ ce galet est déjà attribué — relâche et actionne le bon … ",
                      end="", flush=True)
            else:
                port, bit = diff[0]
                niveau = (octets[port] >> bit) & 1
                attribution[constante] = (port, bit, niveau)
                print(f"{port} bit {bit}, passe à {niveau}")
            while differences(repos, lire_stable()):      # attendre le relâchement
                pass
            if constante in attribution:
                break

    print("\n  À recopier dans config.py :\n")
    for constante, _ in CAPTEURS:
        port, bit, _niveau = attribution[constante]
        print(f"    {constante:21s} = {bit}    # {port.replace(' ', ' GP')}{bit}")

    niveaux = {a[2] for a in attribution.values()}
    if niveaux == {0}:
        print("\n  ✓ Les 4 passent à 0 quand le galet est actionné : contact NO, comme prévu.")
        print("    CAPTEURS_ACTIFS_BAS = True")
    elif niveaux == {1}:
        print("\n  ⚠ Les 4 passent à 1 quand le galet est actionné : c'est le contact NC qui est")
        print("    câblé. Passer sur le contact NO (recommandé : un fil coupé se lit alors")
        print("    « pas en position »), ou mettre CAPTEURS_ACTIFS_BAS = False.")
    else:
        print("\n  ⚠ Les capteurs ne basculent pas tous dans le même sens : câblage NO / NC")
        print("    mélangé. Le programme exige le même sens pour les quatre.")
    hors_port = [c for c, a in attribution.items() if a[0] != "0x26 B"]
    if hors_port:
        print("\n  ⚠ Pas sur le 0x26 port B : " + ", ".join(hors_port))
        print("    → me le signaler : il faut adapter libs/entrees.py, pas seulement config.py.")
    print()


def mode_direct() -> None:
    depart = lire()
    bascules = {}
    precedent = dict(depart)
    print("  Bits affichés 7654 3210. Ctrl+C pour le bilan.\n")
    print("  0x26 A      0x26 B      0x24 B      ont bougé")
    try:
        while True:
            octets = lire()
            for port, bit in differences(precedent, octets):
                bascules[(port, bit)] = bascules.get((port, bit), 0) + 1
            precedent = octets
            liste = " ".join(f"{port.replace(' ', '')}{bit}" for (port, bit) in sorted(bascules))
            print("\r  " + "   ".join(bits(octets[port]) for port in PORTS) + f"   {liste:40s}",
                  end="", flush=True)
            time.sleep(0.02)
    except KeyboardInterrupt:
        print("\n\n  Bilan — bits qui ont changé :")
        if not bascules:
            print("    aucun.")
        for (port, bit), nombre in sorted(bascules.items()):
            print(f"    {port} bit {bit} : {nombre} changement(s), "
                  f"valait {(depart[port] >> bit) & 1} au lancement")
        print()


try:
    if "--direct" in sys.argv:
        mode_direct()
    else:
        mode_attribution()
except KeyboardInterrupt:
    print("\n  Abandonné.\n")
finally:
    materiel.fermer()
