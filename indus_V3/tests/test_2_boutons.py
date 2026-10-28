# -*- coding: utf-8 -*-
"""
test_2_boutons.py — Aperçu en direct des 9 boutons.

Lecture seule : aucun relais, aucun ENA n'est écrit.

    python3 tests/test_2_boutons.py                 APERÇU (par défaut)
    python3 tests/test_2_boutons.py --attribution   refaire la correspondance

APERÇU : chaque bouton a son voyant et son compteur d'appuis, selon config.py.
Un appui = le bon voyant s'allume et son compteur augmente de 1. Un appui
maintenu ne compte qu'UN appui. Ctrl+C pour le bilan.

ATTRIBUTION : à faire au premier montage de la V3 (les 2 boutons ROTATION −
sont nouveaux, l'ancien POSITION devient ROTATION +). Le script nomme une
fonction, tu appuies sur le bouton voulu, il affiche les lignes BTN_* à
recopier dans config.py. Il écoute les trois ports d'entrée.
"""

import sys
import time

import _commun
from _commun import bits, cfg, titre, voyant
from libs.entrees import CABLAGE_BOUTONS, NOMS_BOUTONS, Entrees, Filtre
from libs.materiel import PORT_B

_ACTIONS = {"bridage": ("BRI", "BRIDAGE"), "rotation_plus": ("ROT+", "ROTATION +"),
            "rotation_moins": ("ROT−", "ROTATION −"), "coupe": ("COU", "COUPE")}
_POSTES = {"mere": ("M", "MÈRE"), "fille": ("F", "FILLE")}


def _noms(nom: str) -> tuple:
    """(abrégé, libellé) d'un bouton."""
    if nom == "acquittement":
        return "ACQ", "ACQUITTEMENT"
    action, _, poste = nom.rpartition("_")
    return (f"{_ACTIONS[action][0]}.{_POSTES[poste][0]}",
            f"{_ACTIONS[action][1]} {_POSTES[poste][1]}")


ABREGES = {nom: _noms(nom)[0] for nom in NOMS_BOUTONS}
LIBELLES = {nom: _noms(nom)[1] for nom in NOMS_BOUTONS}
CONSTANTES = {nom: "BTN_" + nom.upper() for nom in NOMS_BOUTONS}
# Port attendu par le programme pour chaque bouton (libs/entrees.py) : « 0x24_B » → (« 0x24 », « B »)
PORT_ATTENDU = {nom: tuple(source.split("_")) for nom, (source, _) in CABLAGE_BOUTONS.items()}


def mode_direct(materiel) -> None:
    # Ligne tenue sous 80 caractères : plus large, le terminal de Geany la coupe
    # en deux et le retour chariot réécrit une ligne de plus à chaque tour.
    print("  Appuyer une fois sur chaque bouton. Ctrl+C pour le bilan.")
    print("  Octets bruts en hexadécimal (FF = rien d'appuyé).\n")
    print("  " + "".join(f"{ABREGES[n]:>6}" for n in NOMS_BOUTONS) + "   24B 26A 26B")
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
            octets = "  ".join(f"{entrees.octets[cle]:02X}" for cle in ("0x24_B", "0x26_A", "0x26_B"))
            print("\r  " + "".join(f"{c:>6}" for c in ligne) + f"    {octets}", end="", flush=True)
            time.sleep(cfg.PERIODE_BOUCLE_S)
    except KeyboardInterrupt:
        print("\n\n  Bilan :")
        for nom in NOMS_BOUTONS:
            etat = f"✓ {appuis[nom]} appui(s)" if appuis[nom] else "✗ jamais vu"
            print(f"    {LIBELLES[nom]:20s} {etat}")
        print()


def mode_attribution(materiel) -> None:
    # Un filtre par bit brut des trois ports d'entrée : (mcp, port, bit) → Filtre.
    # Un appui = le bit QUITTE son niveau de repos (relevé au lancement) : un
    # bouton câblé en NF, à 0 au repos, est donc trouvé aussi, et signalé.
    filtres = {(mcp, port, bit): Filtre(cfg.ANTI_REBOND_BOUTON_S)
               for mcp, port in (("0x24", "B"), ("0x26", "A"), ("0x26", "B")) for bit in range(8)}

    def lire_octets() -> dict:
        a26, b26 = materiel.entrees.lire_ports()
        return {("0x24", "B"): materiel.relais.lire_port(PORT_B), ("0x26", "A"): a26, ("0x26", "B"): b26}

    repos = lire_octets()

    def lire() -> list:
        """Rafraîchit tous les filtres ; renvoie les (mcp, port, bit) qui viennent d'être appuyés."""
        octets = lire_octets()
        maintenant = time.monotonic()
        fronts = []
        for (mcp, port, bit), filtre in filtres.items():
            masque = 1 << bit
            filtre.maj((octets[(mcp, port)] & masque) != (repos[(mcp, port)] & masque), maintenant)
            if filtre.front:
                fronts.append((mcp, port, bit))
        return fronts

    def texte(cle) -> str:
        return f"{cle[0]} GP{cle[1]}{cle[2]}"

    print("  Au repos : " + "   ".join(f"{m} {p} = {bits(o)}" for (m, p), o in repos.items()))
    a_zero = [(m, p, b) for (m, p), o in repos.items() for b in range(8) if not o & (1 << b)]
    if a_zero:
        print("  ⚠ Bits à 0 AU REPOS : " + ", ".join(texte(c) for c in a_zero))
        print("    Sur le 0x26 port B, ce peut être une fin de course actionnée. Sinon : un bouton")
        print("    enfoncé au lancement (relâcher et relancer), ou câblé en NF (contact à passer en NO).\n")
    print("  Pour chaque fonction annoncée, appuyer sur le bouton voulu.")
    print("  ⚠ Les fins de course du 0x26 port B sont aussi écoutées : ne pas les actionner.")
    print("  Ctrl+C pour abandonner.\n")
    attribution: dict = {}
    for nom in NOMS_BOUTONS:
        print(f"  → Appuie sur le bouton {LIBELLES[nom]:20s} … ", end="", flush=True)
        while True:
            fronts = lire()
            time.sleep(cfg.PERIODE_BOUCLE_S)
            if not fronts:
                continue
            if len(fronts) > 1:
                print("\n    ⚠ plusieurs bits en même temps " + ", ".join(texte(f) for f in fronts)
                      + " — recommence … ", end="", flush=True)
                continue
            deja = [n for n, cle in attribution.items() if cle == fronts[0]]
            if deja:
                print(f"\n    ⚠ ce bouton est déjà attribué à {LIBELLES[deja[0]]} "
                      "— appuie sur un autre … ", end="", flush=True)
                continue
            attribution[nom] = fronts[0]
            print(texte(fronts[0]))
            break

    print("\n  À recopier dans config.py :\n")
    for nom in NOMS_BOUTONS:
        mcp, port, bit = attribution[nom]
        print(f"    {CONSTANTES[nom]:26s} = {bit}    # {mcp} GP{port}{bit}")

    # Le programme attend chaque bouton sur un port précis (libs/entrees.py).
    hors_port = [nom for nom in NOMS_BOUTONS if attribution[nom][:2] != PORT_ATTENDU[nom]]
    if hors_port:
        print("\n  ⚠ Câblage différent de ce que le programme attend :")
        for nom in hors_port:
            mcp, port = PORT_ATTENDU[nom]
            print(f"      {LIBELLES[nom]} est sur {texte(attribution[nom])}, attendu sur le {mcp} port {port}")
        print("    → me le signaler : il faut adapter libs/entrees.py, pas seulement config.py.")
    nf = [nom for nom in NOMS_BOUTONS if attribution[nom] in a_zero]
    if nf:
        print("\n  ⚠ Boutons à 0 au repos (contact NF ?) : " + ", ".join(LIBELLES[n] for n in nf))
        print("    Le programme attend des contacts NO (appui = 0) : passer ces fils sur la borne NO.")
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
