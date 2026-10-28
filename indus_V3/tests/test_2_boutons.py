# -*- coding: utf-8 -*-
"""
test_2_boutons.py — Les 9 boutons, un par un : où chacun est câblé, et dans quel sens.

Lecture seule : aucun relais, aucun ENA n'est écrit. Aucun Ctrl+C nécessaire :
le programme se termine tout seul (dans le terminal de Geany, Ctrl+C ferme la
fenêtre et le résultat est perdu).

    python3 tests/test_2_boutons.py             ATTRIBUTION GUIDÉE (par défaut)
    python3 tests/test_2_boutons.py --apercu    voyants en direct

ATTRIBUTION GUIDÉE
  1. Ne toucher à rien : le programme relève le niveau de repos des trois ports
     d'entrée (0x24 B, 0x26 A, 0x26 B).
  2. Il nomme les boutons un par un. Pour chacun : appuyer, puis relâcher. Il
     note le bit qui a quitté son niveau de repos, et ce niveau de repos :
        repos à 1, appui à 0 → contact NO (le cas prévu, BOUTONS_ACTIFS_BAS = True)
        repos à 0, appui à 1 → contact NF                (BOUTONS_ACTIFS_BAS = False)
     Un bouton sans réaction en ATTENTE_MAX_S est noté « non vu » ; on passe au suivant.
  3. À la fin : le tableau complet, les lignes à recopier dans config.py, et les
     incohérences éventuelles. Tout est aussi ENREGISTRÉ dans
     logs/boutons_<date>_<heure>.txt.

APERÇU (--apercu) : un voyant et un compteur par bouton, selon config.py. Le
programme s'arrête seul après APERCU_INACTIVITE_S sans aucun appui, et affiche
le bilan.
"""

import sys
import time
from pathlib import Path

import _commun
from _commun import bits, cfg, titre, voyant
from libs.entrees import CABLAGE_BOUTONS, NOMS_BOUTONS, Entrees, Filtre
from libs.materiel import PORT_B

ATTENTE_MAX_S = 30.0          # attente d'un appui, par bouton
APERCU_INACTIVITE_S = 20.0    # l'aperçu s'arrête après ce temps sans appui
FICHIER = Path(cfg.CHEMIN_JOURNAL).parent / f"boutons_{time.strftime('%Y%m%d_%H%M%S')}.txt"

_ACTIONS = {"bridage": ("BRI", "BRIDAGE"), "rotation_plus": ("ROT+", "ROTATION +"),
            "rotation_moins": ("ROT−", "ROTATION −"), "coupe": ("COU", "COUPE")}
_POSTES = {"mere": ("M", "MÈRE"), "fille": ("F", "FILLE")}
PORTS = (("0x24", "B"), ("0x26", "A"), ("0x26", "B"))


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


def texte(cle) -> str:
    return f"{cle[0]} GP{cle[1]}{cle[2]}"


def lire_octets(materiel) -> dict:
    a26, b26 = materiel.entrees.lire_ports()
    return {("0x24", "B"): materiel.relais.lire_port(PORT_B), ("0x26", "A"): a26, ("0x26", "B"): b26}


def lire_repos(materiel) -> dict:
    """Niveau de repos : 25 lectures identiques de suite (≈ 0,25 s sans aucun changement)."""
    precedent, identiques = lire_octets(materiel), 0
    while identiques < 25:
        time.sleep(0.01)
        octets = lire_octets(materiel)
        identiques = identiques + 1 if octets == precedent else 0
        precedent = octets
    return precedent


def mode_attribution(materiel) -> None:
    print("  NE TOUCHER À RIEN : relevé du niveau de repos…")
    repos = lire_repos(materiel)
    for (mcp, port), octet in repos.items():
        print(f"    {mcp} port {port} au repos : {bits(octet)}")

    # Un appui = le bit QUITTE son niveau de repos, quel que soit ce niveau :
    # un contact NO comme un contact NF est trouvé.
    filtres = {(mcp, port, bit): Filtre(cfg.ANTI_REBOND_BOUTON_S) for mcp, port in PORTS for bit in range(8)}

    def lire() -> tuple:
        """Rafraîchit les filtres. Renvoie (bits qui viennent de quitter le repos, bits hors repos)."""
        octets = lire_octets(materiel)
        maintenant = time.monotonic()
        fronts, hors_repos = [], []
        for (mcp, port, bit), filtre in filtres.items():
            masque = 1 << bit
            filtre.maj((octets[(mcp, port)] & masque) != (repos[(mcp, port)] & masque), maintenant)
            if filtre.front:
                fronts.append((mcp, port, bit))
            if filtre.stable:
                hors_repos.append((mcp, port, bit))
        return fronts, hors_repos

    def attendre_relachement() -> None:
        debut = time.monotonic()
        while time.monotonic() - debut < ATTENTE_MAX_S:
            if not lire()[1]:
                return
            time.sleep(cfg.PERIODE_BOUCLE_S)

    print(f"\n  Pour chaque bouton annoncé : APPUYER puis RELÂCHER. {ATTENTE_MAX_S:.0f} s maximum par bouton.")
    print("  ⚠ Ne pas actionner les fins de course (elles sont sur le 0x26 port B).\n")
    attribution: dict = {}       # nom → (mcp, port, bit) ou None
    lire()                       # premier tour : initialise les filtres
    for numero, nom in enumerate(NOMS_BOUTONS, 1):
        print(f"  {numero}/{len(NOMS_BOUTONS)}  Appuie sur  {LIBELLES[nom]:20s} … ", end="", flush=True)
        debut = time.monotonic()
        trouve = None
        while time.monotonic() - debut < ATTENTE_MAX_S:
            fronts, _ = lire()
            time.sleep(cfg.PERIODE_BOUCLE_S)
            if not fronts:
                continue
            if len(fronts) > 1:
                print("\n        ⚠ plusieurs bits ensemble " + ", ".join(texte(f) for f in fronts)
                      + " — relâche tout et recommence … ", end="", flush=True)
                attendre_relachement()
                continue
            deja = [n for n, cle in attribution.items() if cle == fronts[0]]
            if deja:
                print(f"\n        ⚠ déjà vu pour {LIBELLES[deja[0]]} — appuie sur le bon bouton … ",
                      end="", flush=True)
                attendre_relachement()
                continue
            trouve = fronts[0]
            break
        attribution[nom] = trouve
        if trouve is None:
            print("NON VU")
        else:
            niveau = (repos[trouve[:2]] >> trouve[2]) & 1
            print(f"{texte(trouve)}  (repos {niveau}, {'NO' if niveau else 'NF'})")
            attendre_relachement()

    afficher_resultat(attribution, repos)


def afficher_resultat(attribution: dict, repos: dict) -> None:
    lignes = ["┌─ RÉSULTAT DES BOUTONS " + "─" * 55,
              "│ bouton                 entrée          repos  contact",]
    for nom in NOMS_BOUTONS:
        cle = attribution[nom]
        if cle is None:
            lignes.append(f"│ {LIBELLES[nom]:22s} NON VU")
            continue
        niveau = (repos[cle[:2]] >> cle[2]) & 1
        lignes.append(f"│ {LIBELLES[nom]:22s} {texte(cle):14s}    {niveau}     {'NO' if niveau else 'NF'}")

    lignes += ["│", "│ À recopier dans config.py :"]
    for nom in NOMS_BOUTONS:
        cle = attribution[nom]
        if cle is not None:
            lignes.append(f"│   {CONSTANTES[nom]:26s} = {cle[2]}    # {texte(cle)}")

    vus = [cle for cle in attribution.values() if cle is not None]
    niveaux = {(repos[cle[:2]] >> cle[2]) & 1 for cle in vus}
    lignes.append("│")
    if niveaux == {1}:
        lignes.append("│   BOUTONS_ACTIFS_BAS = True     # repos à 1, appui à 0 : contacts NO")
    elif niveaux == {0}:
        lignes.append("│   BOUTONS_ACTIFS_BAS = False    # repos à 0, appui à 1 : contacts NF")
        lignes.append("│ ⚠ Avec des contacts NF, un fil COUPÉ se lit comme un bouton APPUYÉ : une")
        lignes.append("│   coupure pendant une rotation la fait continuer jusqu'à la butée ; une coupure")
        lignes.append("│   du fil COUPE déclenche une coupe (mandrin fermé). Des contacts NO sont sûrs.")
    elif niveaux:
        lignes.append("│ ⚠ Contacts NO et NF MÉLANGÉS : le programme exige le même sens pour les 9.")
        lignes.append("│   Repasser les boutons sur le même type de contact.")

    problemes = []
    for nom in NOMS_BOUTONS:
        cle = attribution[nom]
        if cle is None:
            problemes.append(f"{LIBELLES[nom]} : aucune réaction (câblage, bouton, ou bit déjà à l'état appuyé)")
        elif cle[:2] != PORT_ATTENDU[nom]:
            mcp, port = PORT_ATTENDU[nom]
            problemes.append(f"{LIBELLES[nom]} est sur {texte(cle)}, le programme l'attend sur le {mcp} port {port}")
    if problemes:
        lignes += ["│", "│ ⚠ À me signaler :"]
        lignes += [f"│   - {p}" for p in problemes]
    lignes.append("└" + "─" * 78)

    print()
    for ligne in lignes:
        print("  " + ligne)
    try:
        FICHIER.parent.mkdir(parents=True, exist_ok=True)
        FICHIER.write_text("\n".join(lignes) + "\n", encoding="utf-8")
        print(f"\n  Enregistré dans : {FICHIER}")
    except OSError as erreur:
        print(f"\n  (résultat non enregistré : {erreur})")


def mode_apercu(materiel) -> None:
    # Ligne tenue sous 80 caractères : plus large, le terminal de Geany la coupe
    # en deux et le retour chariot réécrit une ligne de plus à chaque tour.
    print(f"  Appuyer sur les boutons. Arrêt automatique après {APERCU_INACTIVITE_S:.0f} s sans appui.")
    print("  Octets bruts en hexadécimal.\n")
    print("  " + "".join(f"{ABREGES[n]:>6}" for n in NOMS_BOUTONS) + "   24B 26A 26B")
    entrees = Entrees(materiel.relais, materiel.entrees)
    appuis = {nom: 0 for nom in NOMS_BOUTONS}
    dernier_changement = time.monotonic()
    precedent = None
    while time.monotonic() - dernier_changement < APERCU_INACTIVITE_S:
        entrees.rafraichir(time.monotonic())
        ligne = []
        for nom in NOMS_BOUTONS:
            if entrees.appui(nom):
                appuis[nom] += 1
            ligne.append(f"{voyant(entrees.boutons[nom].stable)}{appuis[nom]:>3}")
        if entrees.octets != precedent:
            dernier_changement = time.monotonic()
            precedent = dict(entrees.octets)
        octets = "  ".join(f"{entrees.octets[cle]:02X}" for cle in ("0x24_B", "0x26_A", "0x26_B"))
        print("\r  " + "".join(f"{c:>6}" for c in ligne) + f"    {octets}", end="", flush=True)
        time.sleep(cfg.PERIODE_BOUCLE_S)
    print("\n\n  Bilan :")
    for nom in NOMS_BOUTONS:
        etat = f"✓ {appuis[nom]} appui(s)" if appuis[nom] else "✗ jamais vu"
        print(f"    {LIBELLES[nom]:20s} {etat}")


titre("TEST 2 — BOUTONS")
materiel = _commun.ouvrir_lecture_seule()
try:
    if "--apercu" in sys.argv:
        mode_apercu(materiel)
    else:
        mode_attribution(materiel)
except KeyboardInterrupt:
    print("\n  Abandonné.")
finally:
    materiel.fermer()
    print()
