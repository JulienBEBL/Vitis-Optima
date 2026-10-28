# -*- coding: utf-8 -*-
"""
test_3_capteurs.py — Aperçu en direct des 4 butées de rotation (fins de course).

Lecture seule : aucun relais, aucun ENA n'est écrit.

Lancer depuis Geany (F5). Un menu propose :
    1 = APERÇU des 4 butées selon config.py (par défaut)
    2 = ATTRIBUTION : refaire la correspondance
    3 = DIRECT : bits bruts de tous les ports

APERÇU : un voyant par butée, selon config.py. Galet actionné = voyant allumé.
Signale si les deux butées d'un même poste sont actives ensemble (ce serait un
défaut D2). Sert aussi au test de débranchement : galet actionné, débrancher le
connecteur → le voyant doit S'ÉTEINDRE. Arrêt automatique après INACTIVITE_S
sans aucun changement, puis bilan (dans Geany, Ctrl+C ferme la fenêtre).

Mode ATTRIBUTION (à faire au premier montage de la V3 : les capteurs ont été
déplacés sur la rotation du mandrin) : le script nomme une butée (« MÈRE —
butée HORAIRE »…),
tu actionnes à la main le galet correspondant puis tu le relâches. Il note sur
quel bit ça arrive et dans quel sens le bit bascule. À la fin il affiche les
lignes CAP_* à recopier dans config.py. Il écoute tous les bits des ports
d'entrée, quelle que soit la config actuelle. Le menu demande quel(s) poste(s) : une
butée non branchée est notée « NON VUE » après ATTENTE_GALET_S, et on passe à la suivante.

  Rappel : HORAIRE et ANTIHORAIRE sont les deux bouts de la rotation du
  mandrin, VUS DU CÔTÉ OPÉRATEUR, pour les deux postes. La butée HORAIRE est
  celle que le mandrin atteint en tournant dans le sens des aiguilles d'une
  montre. test_5_moteur.py vérifie ensuite que le moteur est d'accord.

Mode DIRECT : les 8 bits bruts de chaque port et la liste de ceux qui ont
bougé. Sert aussi au test de débranchement : galet actionné, débrancher le
connecteur → le bit doit revenir à 1 (repli sûr du contact NO).
"""


import time

import _commun
from _commun import bits, cfg, titre, voyant
from libs.entrees import Entrees

PORTS = ("0x26 A", "0x26 B", "0x24 B")
PERIODE_S = 0.01
LECTURES_STABLES = 5      # un changement est retenu après 5 lectures identiques (50 ms)
INACTIVITE_S = 20.0       # aperçu et mode direct : arrêt après ce temps sans changement
ATTENTE_GALET_S = 60.0    # attribution : attente d'un galet ; au-delà, butée notée NON VUE

CAPTEURS = (("CAP_MERE_HORAIRE", "MÈRE  — butée HORAIRE"),
            ("CAP_MERE_ANTIHORAIRE", "MÈRE  — butée ANTIHORAIRE"),
            ("CAP_FILLE_HORAIRE", "FILLE — butée HORAIRE"),
            ("CAP_FILLE_ANTIHORAIRE", "FILLE — butée ANTIHORAIRE"))

titre("TEST 3 — BUTÉES DE ROTATION")
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
    noms = _commun.choisir_postes("Butées de quel(s) poste(s) ? (seulement celles qui sont branchées)")
    capteurs = [(c, l) for c, l in CAPTEURS if any(f"_{n.upper()}_" in c for n in noms)]
    print("\n  Tous les galets LIBRES pour commencer. Pour chaque butée annoncée : actionner")
    print(f"  le galet à la main, puis le relâcher. {ATTENTE_GALET_S:.0f} s maximum par butée.\n")
    repos = lire_stable()
    print(f"  Au repos : 0x26 A = {bits(repos['0x26 A'])}   0x26 B = {bits(repos['0x26 B'])}\n")

    def attendre_relachement() -> None:
        debut = time.monotonic()
        while differences(repos, lire_stable()) and time.monotonic() - debut < ATTENTE_GALET_S:
            pass

    attribution = {}          # constante → (port, bit, niveau galet actionné)
    for constante, libelle in capteurs:
        print(f"  → Actionne le galet {libelle:26s} … ", end="", flush=True)
        debut = time.monotonic()
        while constante not in attribution and time.monotonic() - debut < ATTENTE_GALET_S:
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
            attendre_relachement()
        if constante not in attribution:
            print("NON VU")

    lignes = ["┌─ RÉSULTAT DES BUTÉES " + "─" * 56]
    for constante, libelle in capteurs:
        if constante in attribution:
            port, bit, _niveau = attribution[constante]
            lignes.append(f"│   {constante:22s} = {bit}    # {port.replace(' ', ' GP')}{bit}")
        else:
            lignes.append(f"│   {constante:22s} : NON VU ({libelle.strip()}) — fil, connecteur ou capteur")
    niveaux = {a[2] for a in attribution.values()}
    if niveaux == {0}:
        lignes.append("│ ✓ Passent à 0 quand le galet est actionné : contact NO, comme prévu.")
    elif niveaux == {1}:
        lignes.append("│ ⚠ Passent à 1 quand le galet est actionné : contact NC câblé. Passer sur le NO")
        lignes.append("│   (un fil coupé se lit alors « pas en butée »).")
    elif niveaux:
        lignes.append("│ ⚠ Contacts NO et NC mélangés : le programme exige le même sens pour toutes.")
    hors_port = [c for c, a in attribution.items() if a[0] != "0x26 B"]
    if hors_port:
        lignes.append("│ ⚠ Pas sur le 0x26 port B : " + ", ".join(hors_port) + " — me le signaler.")
    absentes = [c for c, _ in CAPTEURS if c not in dict(capteurs)]
    if absentes:
        lignes.append("│ Non testées (poste non choisi) : " + ", ".join(absentes))
    lignes.append("│ Si une butée du poste prend un bit donné à l'autre poste dans config.py,")
    lignes.append("│ donner à l'autre poste les bits restants (pas deux butées sur un bit).")
    lignes.append("└" + "─" * 78)
    print()
    for ligne in lignes:
        print("  " + ligne)
    fichier = _commun.fichier_resultat("butees")
    _commun.enregistrer(fichier, lignes)
    print(f"\n  Enregistré dans : {fichier}\n")


def mode_direct() -> None:
    depart = lire()
    bascules = {}
    precedent = dict(depart)
    print(f"  Bits affichés 7654 3210. Arrêt automatique après {INACTIVITE_S:.0f} s sans changement.\n")
    print("  0x26 A      0x26 B      0x24 B      ont bougé")
    dernier_changement = time.monotonic()
    try:
        while time.monotonic() - dernier_changement < INACTIVITE_S:
            octets = lire()
            for port, bit in differences(precedent, octets):
                bascules[(port, bit)] = bascules.get((port, bit), 0) + 1
                dernier_changement = time.monotonic()
            precedent = octets
            liste = " ".join(f"{port.replace(' ', '')}{bit}" for (port, bit) in sorted(bascules))
            print("\r  " + "   ".join(bits(octets[port]) for port in PORTS) + f"   {liste:40s}",
                  end="", flush=True)
            time.sleep(0.02)
    finally:
        print("\n\n  Bilan — bits qui ont changé :")
        if not bascules:
            print("    aucun.")
        for (port, bit), nombre in sorted(bascules.items()):
            print(f"    {port} bit {bit} : {nombre} changement(s), "
                  f"valait {(depart[port] >> bit) & 1} au lancement")
        print()


def mode_apercu() -> None:
    cles = [(poste, sens) for poste in cfg.POSTES for sens in (cfg.SENS_ANTIHORAIRE, cfg.SENS_HORAIRE)]
    entrees = Entrees(materiel.relais, materiel.entrees)
    vus = {cle: False for cle in cles}
    d2_vu = False
    print(f"  Actionner les galets. Arrêt automatique après {INACTIVITE_S:.0f} s sans changement.\n")
    print("  MÈRE anti.   MÈRE hor.    FILLE anti.  FILLE hor.    0x26 B")
    dernier_changement = time.monotonic()
    precedent = None
    try:
        while time.monotonic() - dernier_changement < INACTIVITE_S:
            entrees.rafraichir(time.monotonic())
            if entrees.octets["0x26_B"] != precedent:
                precedent = entrees.octets["0x26_B"]
                dernier_changement = time.monotonic()
            alerte = ""
            for poste in cfg.POSTES:
                if all(entrees.butee(poste, sens).stable for sens in cfg.SENS):
                    alerte = f"⚠ D2 {poste}"
                    d2_vu = True
            for cle in cles:
                vus[cle] |= entrees.butees[cle].stable
            print("\r  " + "".join(f"    {voyant(entrees.butees[cle].stable)}       " for cle in cles)
                  + f" {bits(entrees.octets['0x26_B'])}  {alerte:10s}", end="", flush=True)
            time.sleep(cfg.PERIODE_BOUCLE_S)
    finally:
        print("\n\n  Bilan :")
        for (poste, sens), vu in vus.items():
            print(f"    {poste:6s} {sens:12s} {'✓ vue active' if vu else '✗ jamais vue active'}")
        if d2_vu:
            print("    ⚠ les deux butées d'un même poste ont été vues actives ensemble")
        print()


try:
    mode = _commun.menu("Que faire ?", {"1": "APERÇU des butées", "2": "ATTRIBUTION (le câblage a changé)",
                                         "3": "DIRECT : bits bruts"}, "1")
    {"1": mode_apercu, "2": mode_attribution, "3": mode_direct}[mode]()
except KeyboardInterrupt:
    print("\n  Abandonné.\n")
finally:
    materiel.fermer()
