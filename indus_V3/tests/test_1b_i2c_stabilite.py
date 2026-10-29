# -*- coding: utf-8 -*-
"""
test_1b_i2c_stabilite.py — Endurance du bus I2C et des trois MCP23017.

Lancer depuis Geany (F5). Le menu demande la durée et le mode :
  1 = BUS SEUL : rien ne bouge (relais à 0, moteurs libres) ; le bus est lu et
      écrit en continu, aussi vite que possible.
  2 = BUS + MOTEURS : les postes branchés font des allers-retours butée à butée
      pendant tout le test (le vrai programme), pour mesurer le bus AVEC les
      parasites des drivers de puissance — la situation réelle.
Arrêt à la fin de la durée, ou plus tôt par un appui sur ACQUITTEMENT.

Ce qui est mesuré, par MCP :
  - ERREURS : chaque transaction ratée (les nouvelles tentatives automatiques
    du programme sont COUPÉES pendant ce test : on voit tout) ;
  - ÉCRITURE / RELECTURE : un motif est écrit dans les registres DEFVAL (sans
    effet sur les broches : les interruptions sont désactivées) puis relu ;
  - CONFIGURATION : IODIR, GPPU et latchs de sortie relus régulièrement — une
    perte de configuration est comptée puis réparée (c'est le défaut D7) ;
  - PARASITES : tout changement d'une entrée que personne ne touche (boutons,
    butées des postes immobiles) ;
  - TEMPS DE LECTURE des butées (0x26) : moyenne, 99 % et pire cas.
À la fin : un verdict STABLE / À SURVEILLER / INSTABLE, et le RÉCAPITULATIF
enregistré dans logs/i2c_<date>_<heure>.txt.
"""

import time

import _commun
from _commun import cfg, confirmer, menu, titre
from libs import entrees as E
from libs.materiel import PORT_B, frequence_bus_i2c
from libs.poste import PRET, Defaut

_DEFVALA = 0x06
MOTIFS = (0x55, 0xAA, 0x00, 0xFF, 0x0F, 0xF0)
PERIODE_CONFIG = 200            # tours entre deux relectures de configuration
H, A = cfg.SENS_HORAIRE, cfg.SENS_ANTIHORAIRE


def nom_entree(source: str, bit: int) -> str:
    for nom, (s, b) in E.CABLAGE_BOUTONS.items():
        if (s, b) == (source, bit):
            return f"bouton {nom}"
    if source == "0x26_B":
        for (poste, sens), b in E.CABLAGE_BUTEES.items():
            if b == bit:
                return f"butée {poste} {sens}"
    return "non câblé"


titre("TEST 1b — ENDURANCE DU BUS I2C ET DES 3 MCP")
duree_min = {"1": 1, "2": 5, "3": 15, "4": 60}[
    menu("Durée du test ?", {"1": "1 minute", "2": "5 minutes", "3": "15 minutes", "4": "1 heure"}, "2")]
avec_moteurs = menu("Mode ?", {"1": "BUS SEUL (rien ne bouge)",
                               "2": "BUS + MOTEURS en mouvement (situation réelle)"}, "1") == "2"
noms = _commun.choisir_postes("Postes branchés (moteurs) ?") if avec_moteurs else ()

materiel = _commun.ouvrir(avec_gpio=True)
cfg.I2C_RETRIES = 0             # chaque erreur doit être vue, pas retentée en silence
puces = {"0x24": materiel.relais, "0x25": materiel.drivers, "0x26": materiel.entrees}
stats = {nom: {"transactions": 0, "erreurs": 0, "relectures_fausses": 0, "pertes_config": 0}
         for nom in puces}
parasites = {}                  # (source, bit) → nombre de changements
# Temps de lecture des butées (0x26) : histogramme par pas de 10 µs (un test d'une
# heure ferait des millions de mesures : on ne les garde pas une par une).
latence = {"nombre": 0, "somme": 0.0, "pire": 0.0, "histo": [0] * 2001}   # 0 à 20 ms


def noter_latence(duree_s: float) -> None:
    latence["nombre"] += 1
    latence["somme"] += duree_s
    latence["pire"] = max(latence["pire"], duree_s)
    latence["histo"][min(int(duree_s * 100_000), 2000)] += 1


def latence_99() -> float:
    seuil, cumul = 0.99 * latence["nombre"], 0
    for case, nombre in enumerate(latence["histo"]):
        cumul += nombre
        if cumul >= seuil:
            return (case + 1) / 100_000
    return latence["pire"]
postes, entrees_p, buzzer = {}, None, None
resultat = []


def compter(puce: str, operation):
    """Exécute une transaction, la compte ; renvoie son résultat ou None si elle a échoué."""
    stats[puce]["transactions"] += 1
    try:
        return operation()
    except OSError:
        stats[puce]["erreurs"] += 1
        return None


def texte_frequence() -> str:
    frequence = frequence_bus_i2c()
    return "vitesse inconnue" if frequence is None else f"{frequence / 1000:.0f} kHz"


def verdict() -> str:
    erreurs = sum(s["erreurs"] for s in stats.values())
    fausses = sum(s["relectures_fausses"] for s in stats.values())
    pertes = sum(s["pertes_config"] for s in stats.values())
    if pertes or fausses or erreurs > 10:
        return "INSTABLE"
    if erreurs or parasites:
        return "À SURVEILLER"
    return "STABLE"


def recapitulatif(duree_s: float) -> list:
    total = sum(s["transactions"] for s in stats.values())
    lignes = ["┌─ RÉCAPITULATIF À M'ENVOYER " + "─" * 50,
              f"│ {time.strftime('%Y-%m-%d %H:%M:%S')} — {duree_s / 60:.1f} min, mode "
              f"{'BUS + MOTEURS (' + ', '.join(noms) + ')' if avec_moteurs else 'BUS SEUL'}",
              f"│ bus I2C : {texte_frequence()} — {total} transactions, "
              f"{total / max(duree_s, 1):.0f} par seconde",
              "│",
              "│ MCP    transactions   erreurs   relectures fausses   pertes de config"]
    for nom, s in stats.items():
        taux = 100.0 * s["erreurs"] / max(s["transactions"], 1)
        lignes.append(f"│ {nom}   {s['transactions']:12d}   {s['erreurs']:5d} ({taux:.3f} %)"
                      f"   {s['relectures_fausses']:8d}           {s['pertes_config']:8d}")
    if latence["nombre"]:
        lignes.append(f"│ lecture des butées (0x26) : moyenne {1000 * latence['somme'] / latence['nombre']:.2f} ms, "
                      f"99 % < {1000 * latence_99():.2f} ms, pire {1000 * latence['pire']:.2f} ms")
    if parasites:
        lignes.append("│ parasites sur des entrées que personne ne touchait :")
        for (source, bit), nombre in sorted(parasites.items()):
            lignes.append(f"│   {source} bit {bit} ({nom_entree(source, bit)}) : {nombre} changement(s)")
    else:
        lignes.append("│ aucun parasite sur les entrées")
    for ligne in resultat:
        lignes.append("│ " + ligne)
    lignes.append("│")
    lignes.append(f"│ VERDICT : {verdict()}")
    lignes.append("└" + "─" * 78)
    return lignes


debut = time.monotonic()
fichier = _commun.fichier_resultat("i2c")
try:
    if avec_moteurs:
        if not confirmer("Mandrins vides, zone dégagée : les moteurs vont tourner pendant tout le test. Lancer ?"):
            raise SystemExit("  Non lancé.")
        entrees_p, postes, buzzer = _commun.construire_postes(materiel, noms)
        print("  Initialisation des postes…")
        _commun.initialiser(entrees_p, postes, buzzer)
        sens_suivant = {nom: H for nom in noms}
    print(f"\n  Test en cours pour {duree_min} min — ACQUITTEMENT pour arrêter avant.\n")
    debut = time.monotonic()
    fin = debut + 60 * duree_min
    source_acq, bit_acq = E.CABLAGE_BOUTONS[E.ACQUITTEMENT]
    butees_mobiles = {("0x26_B", E.CABLAGE_BUTEES[(nom, s)]) for nom in noms for s in (H, A)}
    precedents = None
    tour = 0
    prochain_affichage = 0.0
    while time.monotonic() < fin:
        tour += 1
        maintenant = time.monotonic()
        # ── Lectures des entrées (comme la boucle du programme)
        t0 = time.perf_counter()
        ports_26 = compter("0x26", materiel.entrees.lire_ports)
        if ports_26 is not None:
            noter_latence(time.perf_counter() - t0)
        octet_24 = compter("0x24", lambda: materiel.relais.lire_port(PORT_B))
        if ports_26 is not None and octet_24 is not None:
            octets = {"0x24_B": octet_24, "0x26_A": ports_26[0], "0x26_B": ports_26[1]}
            if octets[source_acq] & (1 << bit_acq) == 0 and cfg.BOUTONS_ACTIFS_BAS:
                resultat.append("arrêté par ACQUITTEMENT")
                break
            if precedents is not None:
                for source, octet in octets.items():
                    changes = octet ^ precedents[source]
                    for bit in range(8):
                        if changes & (1 << bit) and (source, bit) not in butees_mobiles:
                            parasites[(source, bit)] = parasites.get((source, bit), 0) + 1
            precedents = octets
        # ── Écriture / relecture d'un motif dans DEFVAL, une puce par tour
        nom = ("0x24", "0x25", "0x26")[tour % 3]
        puce = puces[nom]
        motif = MOTIFS[(tour // 3) % len(MOTIFS)]
        compter(nom, lambda: puce.bus.ecrire(puce.adresse, _DEFVALA, motif))
        compter(nom, lambda: puce.bus.ecrire(puce.adresse, _DEFVALA + 1, motif ^ 0xFF))
        relu = compter(nom, lambda: puce.bus.lire_bloc(puce.adresse, _DEFVALA, 2))
        if relu is not None and list(relu) != [motif, motif ^ 0xFF]:
            stats[nom]["relectures_fausses"] += 1
        # ── Configuration de chaque puce, régulièrement
        if tour % PERIODE_CONFIG == 0:
            for nom_p, puce_p in puces.items():
                ecarts = compter(nom_p, puce_p.ecarts_config)
                if ecarts:
                    stats[nom_p]["pertes_config"] += 1
                    resultat.append(f"{time.monotonic() - debut:6.1f} s — {nom_p} : {', '.join(ecarts)}")
                    compter(nom_p, puce_p.configurer)
        # ── Moteurs : le vrai code des postes, allers-retours butée à butée
        if avec_moteurs:
            try:
                entrees_p.rafraichir(maintenant)
                for nom_p, poste in postes.items():
                    poste.avancer(maintenant)
                    if poste.etat == PRET and maintenant >= poste.libre_a:
                        poste.lancer_rotation(sens_suivant[nom_p])
                        sens_suivant[nom_p] = A if sens_suivant[nom_p] == H else H
                buzzer.avancer(maintenant)
            except OSError:
                stats["0x26"]["erreurs"] += 1
            time.sleep(cfg.PERIODE_BOUCLE_S)
        # ── Affichage, une fois par seconde, sous 80 caractères
        if maintenant >= prochain_affichage:
            prochain_affichage = maintenant + 1.0
            total = sum(s["transactions"] for s in stats.values())
            erreurs = sum(s["erreurs"] for s in stats.values())
            fausses = sum(s["relectures_fausses"] for s in stats.values())
            pertes = sum(s["pertes_config"] for s in stats.values())
            print(f"\r  {maintenant - debut:6.0f} s  {total:9d} trans.  erreurs {erreurs:4d}  relect. {fausses:3d}"
                  f"  config {pertes:2d}  parasites {sum(parasites.values()):4d}", end="", flush=True)
    print()
except Defaut as defaut:
    resultat.append(f"✗ DÉFAUT {defaut.code} pendant le test : {defaut.detail}")
except KeyboardInterrupt:
    resultat.append("interrompu")
finally:
    duree = time.monotonic() - debut
    if postes:
        _commun.arreter_postes(postes)
    for puce in puces.values():                     # DEFVAL remis à 0
        try:
            puce.bus.ecrire(puce.adresse, _DEFVALA, 0)
            puce.bus.ecrire(puce.adresse, _DEFVALA + 1, 0)
        except OSError:
            pass
    materiel.fermer()
    lignes = recapitulatif(duree)
    print()
    for ligne in lignes:
        print("  " + ligne)
    _commun.enregistrer(fichier, lignes)
    print(f"  Enregistré dans : {fichier}")
    print("  Relais à 0, moteurs libres.\n")
