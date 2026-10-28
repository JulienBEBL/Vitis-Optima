# -*- coding: utf-8 -*-
"""
test_2_boutons.py — Les 9 boutons : validation de config.py, ou attribution.

Lecture seule : aucun relais, aucun ENA n'est écrit. Aucun Ctrl+C nécessaire :
le programme se termine tout seul (dans le terminal de Geany, Ctrl+C ferme la
fenêtre et le résultat est perdu). Chaque résultat est aussi ENREGISTRÉ dans
logs/boutons_<date>_<heure>.txt.

    python3 tests/test_2_boutons.py                 VALIDATION (par défaut)
    python3 tests/test_2_boutons.py --attribution   refaire la correspondance
    python3 tests/test_2_boutons.py --apercu        voyants en direct

VALIDATION — vérifie que config.py correspond au câblage
  Le programme nomme les 9 boutons un par un. Pour chacun : appuyer, puis
  relâcher. Il vérifie que C'EST BIEN CE BOUTON-LÀ qui réagit, selon config.py,
  et aucun autre. Pour les 4 boutons de ROTATION, il demande de MAINTENIR 2 s
  et vérifie que le contact ne lâche pas pendant le maintien (un contact qui
  lâche arrêterait la rotation). À la fin : « TOUT EST BON », ou la liste de ce
  qui ne va pas.

ATTRIBUTION — à refaire seulement si le câblage change
  Même déroulé, mais le programme écoute TOUS les bits des trois ports d'entrée
  et note celui qui quitte son niveau de repos (contact NO ou NF). À la fin :
  les lignes BTN_* à recopier dans config.py.

APERÇU (--apercu) : un voyant et un compteur par bouton. Arrêt automatique
après APERCU_INACTIVITE_S sans aucun appui, puis bilan.
"""

import sys
import time
from pathlib import Path

import _commun
from _commun import bits, cfg, titre, voyant
from libs.entrees import CABLAGE_BOUTONS, NOMS_BOUTONS, ROTATION_MOINS, ROTATION_PLUS, Entrees, Filtre
from libs.materiel import PORT_B

ATTENTE_MAX_S = 30.0          # attente d'un appui, par bouton
MAINTIEN_S = 2.0              # validation : durée de maintien des boutons de rotation
APERCU_INACTIVITE_S = 20.0    # l'aperçu s'arrête après ce temps sans appui
FICHIER = Path(cfg.CHEMIN_JOURNAL).parent / f"boutons_{time.strftime('%Y%m%d_%H%M%S')}.txt"

_ACTIONS = {"bridage": ("BRI", "BRIDAGE"), "rotation_plus": ("ROT+", "ROTATION +"),
            "rotation_moins": ("ROT−", "ROTATION −"), "coupe": ("COU", "COUPE")}
_POSTES = {"mere": ("M", "MÈRE"), "fille": ("F", "FILLE")}
PORTS = (("0x24", "B"), ("0x26", "A"), ("0x26", "B"))
ROTATIONS = {f"{action}_{poste}" for poste in cfg.POSTES for action in (ROTATION_PLUS, ROTATION_MOINS)}


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


def texte(cle) -> str:
    """(« 0x24 », « B », 5) → « 0x24 GPB5 »."""
    return f"{cle[0]} GP{cle[1]}{cle[2]}"


def entree_config(nom: str) -> tuple:
    source, bit = CABLAGE_BOUTONS[nom]
    mcp, port = source.split("_")
    return mcp, port, bit


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


def terminer(lignes: list) -> None:
    """Affiche le cadre de résultat et l'enregistre."""
    print()
    for ligne in lignes:
        print("  " + ligne)
    try:
        FICHIER.parent.mkdir(parents=True, exist_ok=True)
        FICHIER.write_text("\n".join(lignes) + "\n", encoding="utf-8")
        print(f"\n  Enregistré dans : {FICHIER}")
    except OSError as erreur:
        print(f"\n  (résultat non enregistré : {erreur})")


# ═══════════════════════════════════════════════════════════════════════════
#  VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

def mode_validation(materiel) -> None:
    entrees = Entrees(materiel.relais, materiel.entrees)

    def tour() -> list:
        """Une lecture ; renvoie les boutons dont l'appui vient d'être retenu."""
        entrees.rafraichir(time.monotonic())
        time.sleep(cfg.PERIODE_BOUCLE_S)
        return [nom for nom in NOMS_BOUTONS if entrees.appui(nom)]

    def appuyes() -> list:
        return [nom for nom in NOMS_BOUTONS if entrees.boutons[nom].stable]

    def attendre_relachement() -> None:
        debut = time.monotonic()
        while appuyes() and time.monotonic() - debut < ATTENTE_MAX_S:
            tour()

    print("  NE TOUCHER À RIEN : vérification du repos…")
    for _ in range(30):
        tour()
    au_repos_appuyes = appuyes()
    if au_repos_appuyes:
        print("  ⚠ Lus APPUYÉS au repos : " + ", ".join(LIBELLES[n] for n in au_repos_appuyes))
    else:
        print("  ✓ Les 9 boutons sont relâchés au repos.")

    print(f"\n  Pour chaque bouton annoncé : APPUYER puis RELÂCHER. {ATTENTE_MAX_S:.0f} s maximum par bouton.")
    print(f"  Boutons de ROTATION : les MAINTENIR {MAINTIEN_S:.0f} s (le programme le dit).\n")
    resultats = {}       # nom → (bon : bool, détail)
    for numero, nom in enumerate(NOMS_BOUTONS, 1):
        rotation = nom in ROTATIONS
        consigne = f"MAINTIENS {MAINTIEN_S:.0f} s" if rotation else "Appuie sur"
        print(f"  {numero}/{len(NOMS_BOUTONS)}  {consigne:12s} {LIBELLES[nom]:20s} … ", end="", flush=True)
        attendre_relachement()
        debut = time.monotonic()
        reagi = []
        while not reagi and time.monotonic() - debut < ATTENTE_MAX_S:
            reagi = tour()
        if not reagi:
            resultats[nom] = (False, f"aucune réaction (attendu sur {texte(entree_config(nom))})")
        elif reagi != [nom]:
            autres = [n for n in reagi if n != nom]
            if nom in reagi:
                resultats[nom] = (False, "a réagi EN MÊME TEMPS que " + ", ".join(LIBELLES[n] for n in autres)
                                  + " (court-circuit, ou deux fonctions sur le même fil)")
            else:
                resultats[nom] = (False, "c'est " + ", ".join(f"{LIBELLES[n]} ({texte(entree_config(n))})"
                                                             for n in reagi)
                                  + " qui a réagi : config.py inversé, ou mauvais bouton appuyé")
        elif rotation:
            # Le maintien : le contact ne doit pas lâcher (lecture BRUTE, comme le
            # programme, qui arrête la rotation au premier relâchement lu).
            pertes, fin = 0, time.monotonic() + MAINTIEN_S
            while time.monotonic() < fin and entrees.boutons[nom].stable:
                tour()
                if not entrees.tenu(nom):
                    pertes += 1
            if time.monotonic() < fin:
                resultats[nom] = (False, f"relâché avant {MAINTIEN_S:.0f} s — à refaire en maintenant")
            elif pertes:
                resultats[nom] = (False, f"le contact a lâché {pertes} fois pendant le maintien : la "
                                         "rotation s'arrêterait (contact, fil, connecteur)")
            else:
                resultats[nom] = (True, f"{texte(entree_config(nom))}, maintien {MAINTIEN_S:.0f} s sans perte")
        else:
            resultats[nom] = (True, texte(entree_config(nom)))
        bon, detail = resultats[nom]
        print(("✓ " if bon else "✗ ") + detail)

    lignes = ["┌─ VALIDATION DES BOUTONS " + "─" * 53]
    for nom in NOMS_BOUTONS:
        bon, detail = resultats[nom]
        lignes.append(f"│ {'✓' if bon else '✗'} {LIBELLES[nom]:20s} {detail}")
    lignes.append("│")
    if au_repos_appuyes:
        lignes.append("│ ✗ Appuyés au repos : " + ", ".join(LIBELLES[n] for n in au_repos_appuyes))
    if all(bon for bon, _ in resultats.values()) and not au_repos_appuyes:
        lignes.append("│ TOUT EST BON : config.py correspond au câblage des 9 boutons.")
    else:
        lignes.append("│ ✗ À CORRIGER — relancer avec --attribution si le câblage a changé.")
    lignes.append("└" + "─" * 78)
    terminer(lignes)


# ═══════════════════════════════════════════════════════════════════════════
#  ATTRIBUTION
# ═══════════════════════════════════════════════════════════════════════════

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

    lignes = ["┌─ RÉSULTAT DES BOUTONS " + "─" * 55,
              "│ bouton                 entrée          repos  contact"]
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
            lignes.append(f'│   {CONSTANTES[nom]:26s} = ("{cle[0]}", "{cle[1]}", {cle[2]})')

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

    problemes = [f"{LIBELLES[nom]} : aucune réaction" for nom in NOMS_BOUTONS if attribution[nom] is None]
    problemes += [f"{LIBELLES[nom]} est sur {texte(cle)}, entrée non câblée sur le PCB"
                  for nom, cle in attribution.items()
                  if cle is not None and cle[2] not in cfg.ENTREES_BOUTONS_CABLEES[cle[:2]]]
    if problemes:
        lignes += ["│", "│ ⚠ À me signaler :"] + [f"│   - {p}" for p in problemes]
    lignes.append("└" + "─" * 78)
    terminer(lignes)


# ═══════════════════════════════════════════════════════════════════════════
#  APERÇU
# ═══════════════════════════════════════════════════════════════════════════

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
    elif "--attribution" in sys.argv:
        mode_attribution(materiel)
    else:
        mode_validation(materiel)
except KeyboardInterrupt:
    print("\n  Abandonné.")
finally:
    materiel.fermer()
    print()
