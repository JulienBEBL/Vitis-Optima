# -*- coding: utf-8 -*-
"""
test_5_moteur.py — Mise en service des moteurs, étape par étape.

⚠ CE TEST FAIT TOURNER LES MOTEURS. Arrêt d'urgence à portée de main, mandrins
   vides. Tests 2 et 3 validés d'abord. DIP des drivers vérifiés (6400 pas/tr,
   voir DRIVER_DIP_SWITCH dans config.py).

Lancer depuis Geany (F5). Tout se fait au clavier, le programme se termine seul.
Chaque étape demande ton accord avant de faire bouger quoi que ce soit, et
utilise les corrections trouvées aux étapes précédentes, même si config.py
n'est pas encore corrigé.

ÉTAPE 1 — QUEL MOTEUR EST QUI (les deux drivers, l'un après l'autre)
  Le programme fait faire au moteur « mère » de config.py un petit aller-retour
  lent (IDENT_DEG, arrêt immédiat sur toute butée). Tu dis quel mandrin a
  tourné, et dans quel SENS il est parti (vu côté opérateur). Puis pareil pour
  le moteur « fille ». → correspondance driver ↔ poste, DIR_VERS_HORAIRE.

ÉTAPE 2 — BUTÉES (poste par poste)
  Rotation lente vers HORAIRE jusqu'à la première butée : est-ce bien la butée
  HORAIRE de config.py ? Puis vers ANTIHORAIRE jusqu'à l'autre. Plage
  approximative. → CAP_* à échanger ou non.

ÉTAPE 3 — REMISE À ZÉRO ET COURSE TOTALE
  Initialisation réelle du programme (passe rapide, recul, passe lente de chaque
  côté, puis centrage), répétée plusieurs fois, les postes choisis ensemble.
  → plage mesurée (PLAGE_NOMINALE_DEG), écart passe rapide / passe lente.

ÉTAPE 4 — BOUTONS ROTATION + / −
  Les vrais boutons, maintenus : départ doux, croisière, arrêt au relâchement,
  arrêt sur butée. Fin automatique après ESSAI_INACTIVITE_S sans rotation.
  → SENS_ROTATION_PLUS.

À la fin : RÉCAPITULATIF avec les lignes à recopier dans config.py, aussi
ENREGISTRÉ dans logs/moteurs_<date>_<heure>.txt (réécrit après chaque étape).
Le réglage des vitesses et des rampes se fait ensuite avec test_6_reglage.py.
"""

import time

import _commun
from _commun import cfg, confirmer, menu, nombre, titre, voyant
from libs import entrees as E
from libs.entrees import ROTATION_MOINS, ROTATION_PLUS, Entrees
from libs.moteur import Axe, PortsDrivers, periodes_rampe
from libs.materiel import Buzzer
from libs.poste import ROTATION, Defaut, Poste

IDENT_DEG = 5.0                 # étape 1 : amplitude de l'aller-retour d'identification
IDENT_VITESSE_DEG_S = 5.0       # étape 1 : vitesse, lente pour bien voir
BUTEE_VITESSE_DEG_S = 10.0      # étape 2 : vitesse de recherche des butées
MESURES_PAR_DEFAUT = 3          # étape 3
ESSAI_INACTIVITE_S = 30.0       # étape 4 : fin automatique après ce temps sans rotation
H, A = cfg.SENS_HORAIRE, cfg.SENS_ANTIHORAIRE

# Les deux emplacements de driver, tels que config.py les attribue aujourd'hui.
DRIVERS = {
    cfg.POSTE_MERE: {"PUL": cfg.PUL_MERE, "DIR": cfg.DIR_MERE, "ENA": cfg.ENA_MERE},
    cfg.POSTE_FILLE: {"PUL": cfg.PUL_FILLE, "DIR": cfg.DIR_FILLE, "ENA": cfg.ENA_FILLE},
}

FICHIER = _commun.fichier_resultat("moteurs")
corrections = []        # lignes « à recopier dans config.py »
journal = [f"TEST 5 — mise en service des moteurs — {time.strftime('%Y-%m-%d %H:%M:%S')}"]


def noter(ligne: str) -> None:
    """Affiche, garde pour le récapitulatif, réécrit le fichier."""
    print(ligne)
    journal.append(ligne.strip("\n"))
    _commun.enregistrer(FICHIER, journal + ["", "À recopier dans config.py :"] + corrections)


def corriger(ligne: str) -> None:
    corrections.append("  " + ligne)
    noter(f"    → config.py : {ligne}")


titre("TEST 5 — MISE EN SERVICE DES MOTEURS")
materiel = _commun.ouvrir(avec_gpio=True)
ports = PortsDrivers(materiel.drivers)
entrees = Entrees(materiel.relais, materiel.entrees)
buzzer = Buzzer(materiel.puce)
axes = {}
postes = {}


def lire_butees() -> dict:
    """État stable des 4 butées (anti-rebond rempli) : (poste, sens) → bool."""
    for _ in range(12):
        entrees.rafraichir(time.monotonic())
        time.sleep(cfg.PERIODE_BOUCLE_S)
    return {cle: filtre.stable for cle, filtre in entrees.butees.items()}


def tourner(axe: Axe, niveau_dir: int, pas: int, vitesse_deg_s: float, surveiller: list) -> tuple:
    """Rotation à vitesse constante (après la rampe), arrêt au budget ou sur la
    première butée de `surveiller` qui s'active (si elle n'était pas déjà active).
    Renvoie (pas faits, butée vue ou None, pas à la détection)."""
    vitesse = vitesse_deg_s * cfg.PAS_PAR_DEGRE
    actives = {cle for cle, actif in lire_butees().items() if actif}
    axe.lancer_niveau(niveau_dir, pas, periodes_rampe(vitesse), 1.0 / vitesse)
    vue, detection = None, None
    try:
        while axe.en_marche:
            entrees.rafraichir(time.monotonic())
            for cle in surveiller:
                filtre = entrees.butees[cle]
                if cle in actives and not filtre.brut:
                    actives.discard(cle)            # butée de départ relâchée : surveillée désormais
                if vue is None and cle not in actives and filtre.consecutifs >= cfg.CAPTEUR_LECTURES_ARRET:
                    vue, detection = cle, axe.pas
                    axe.demander_arret()
            time.sleep(cfg.PERIODE_BOUCLE_S)
    finally:
        axe.demander_arret()
        axe.attendre_fin(cfg.ARRET_THREAD_MAX_S)
    if axe.erreur is not None:
        raise RuntimeError(f"génération d'impulsions interrompue : {axe.erreur}")
    return axe.pas, vue, detection


# ═══════════════════════════════════════════════════════════════════════════
#  ÉTAPE 1 — QUEL MOTEUR EST QUI
# ═══════════════════════════════════════════════════════════════════════════

def etape_identification() -> None:
    noter("\n  ÉTAPE 1 — QUEL MOTEUR EST QUI")
    print(f"  Chaque moteur va faire un aller-retour de {IDENT_DEG:.0f}° à {IDENT_VITESSE_DEG_S:.0f}°/s.")
    print("  Mandrins loin de leurs butées si possible (arrêt immédiat sur une butée de toute façon).")
    if not confirmer("Mandrins vides, zone dégagée, lancer ?"):
        raise SystemExit("  Non lancé.")
    toutes_butees = list(entrees.butees)
    trouve = {}                 # emplacement (nom config) → (poste réel, DIR vers horaire)
    for emplacement, broches in DRIVERS.items():
        axe = Axe(emplacement, materiel.puce, broches["PUL"], broches["DIR"], broches["ENA"], ports)
        axe.exciter()
        time.sleep(cfg.MOTEUR_ENA_AVANT_DIR_S)
        pas = round(IDENT_DEG * cfg.PAS_PAR_DEGRE)
        while True:
            print(f"\n  Driver « {emplacement} » de config.py (PUL {broches['PUL']}, DIR GPA{broches['DIR']}, "
                  f"ENA GPB{broches['ENA']}) : aller…", flush=True)
            faits, vue, _ = tourner(axe, 0, pas, IDENT_VITESSE_DEG_S, toutes_butees)
            if vue:
                print(f"    (arrêt sur la butée {vue[1]} de {vue[0]})")
            time.sleep(0.5)
            print("    …retour", flush=True)
            tourner(axe, 1, faits, IDENT_VITESSE_DEG_S, [])
            qui = menu("Quel mandrin a tourné ?", {"m": "mère", "f": "fille", "0": "aucun",
                                                    "2": "les deux", "r": "recommencer"}, "r")
            if qui == "r":
                continue
            if qui == "0":
                axe.liberer()
                raise SystemExit("  ✗ Aucun mandrin n'a tourné : alimentation du driver, LED rouge, ENA, "
                                 "câble moteur, DIP. Relancer après correction.")
            if qui == "2":
                axe.liberer()
                raise SystemExit("  ✗ Les deux ont tourné : deux drivers sur le même PUL ou le même câble. "
                                 "À corriger avant de continuer.")
            sens = menu("À l'ALLER, dans quel sens est parti ce mandrin (vu côté opérateur) ?",
                        {"h": "horaire", "a": "antihoraire", "r": "recommencer"}, "r")
            if sens == "r":
                continue
            break
        axe.liberer()
        poste = cfg.POSTE_MERE if qui == "m" else cfg.POSTE_FILLE
        trouve[emplacement] = (poste, 0 if sens == "h" else 1)

    reels = [p for p, _ in trouve.values()]
    if len(set(reels)) != 2:
        raise SystemExit(f"  ✗ Les deux drivers font tourner le même mandrin ({reels[0]}) : câblage à revoir.")
    if trouve[cfg.POSTE_MERE][0] != cfg.POSTE_MERE:
        noter("  ⚠ Drivers INVERSÉS : le driver « mère » de config.py fait tourner la fille.")
        mere, fille = DRIVERS[cfg.POSTE_FILLE], DRIVERS[cfg.POSTE_MERE]
        for nom, valeur in (("PUL_MERE", mere["PUL"]), ("DIR_MERE", mere["DIR"]), ("ENA_MERE", mere["ENA"]),
                            ("PUL_FILLE", fille["PUL"]), ("DIR_FILLE", fille["DIR"]), ("ENA_FILLE", fille["ENA"])):
            corriger(f"{nom} = {valeur}")
            setattr(cfg, nom, valeur)
    else:
        noter("  ✓ Driver « mère » → mandrin mère, driver « fille » → mandrin fille.")

    for poste, niveau in trouve.values():
        actuel = cfg.DIR_VERS_HORAIRE[poste]
        if niveau == actuel:
            noter(f"  ✓ {poste} : sens de rotation conforme (DIR vers horaire = {niveau})")
        else:
            noter(f"  ⚠ {poste} : sens de rotation INVERSÉ")
            cfg.DIR_VERS_HORAIRE[poste] = niveau
            cfg.DIR_VERS_ANTIHORAIRE[poste] = 1 - niveau
    if any(niveau != DIR_ORIGINE[poste] for poste, niveau in cfg.DIR_VERS_HORAIRE.items()):
        corriger(f"DIR_VERS_HORAIRE = {{POSTE_MERE: {cfg.DIR_VERS_HORAIRE[cfg.POSTE_MERE]}, "
                 f"POSTE_FILLE: {cfg.DIR_VERS_HORAIRE[cfg.POSTE_FILLE]}}}")


# ═══════════════════════════════════════════════════════════════════════════
#  ÉTAPE 2 — BUTÉES
# ═══════════════════════════════════════════════════════════════════════════

def construire_axes() -> None:
    """Les deux moteurs, avec la correspondance (corrigée ou non) de config.py."""
    for poste, (pul, dir_, ena) in ((cfg.POSTE_MERE, (cfg.PUL_MERE, cfg.DIR_MERE, cfg.ENA_MERE)),
                                    (cfg.POSTE_FILLE, (cfg.PUL_FILLE, cfg.DIR_FILLE, cfg.ENA_FILLE))):
        axes[poste] = Axe(poste, materiel.puce, pul, dir_, ena, ports)


def etape_butees(noms: tuple) -> None:
    noter("\n  ÉTAPE 2 — BUTÉES")
    budget = round((max(cfg.PLAGE_NOMINALE_DEG.values()) * 1.5) * cfg.PAS_PAR_DEGRE)
    print(f"  Rotation à {BUTEE_VITESSE_DEG_S:.0f}°/s jusqu'à la butée HORAIRE, puis jusqu'à l'ANTIHORAIRE.")
    print(f"  Borne de sécurité : {budget / cfg.PAS_PAR_DEGRE:.0f}° par trajet.")
    for poste in noms:
        if not confirmer(f"Poste {poste.upper()} : lancer la recherche des butées ?"):
            continue
        axe = axes[poste]
        axe.exciter()
        time.sleep(cfg.MOTEUR_ENA_AVANT_DIR_S)
        siennes = [(poste, H), (poste, A)]
        vues = {}
        for sens in (H, A):
            niveau = cfg.DIR_VERS_HORAIRE[poste] if sens == H else cfg.DIR_VERS_ANTIHORAIRE[poste]
            print(f"    {poste} → {sens}…", end="", flush=True)
            faits, vue, detection = tourner(axe, niveau, budget, BUTEE_VITESSE_DEG_S, siennes)
            if vue is None:
                print(" rien")
                noter(f"  ✗ {poste} : aucune butée vue en tournant {sens} sur {faits / cfg.PAS_PAR_DEGRE:.0f}° "
                      "— capteur non câblé ou mort, ou mauvais sens de rotation (étape 1)")
                axe.liberer()
                raise SystemExit(1)
            print(f" butée « {vue[1]} » de config.py vue après {detection / cfg.PAS_PAR_DEGRE:.1f}°")
            vues[sens] = (vue[1], detection)
            time.sleep(0.5)
        axe.liberer()
        if vues[H][0] == H and vues[A][0] == A:
            noter(f"  ✓ {poste} : butées conformes ; plage ≈ {vues[A][1] / cfg.PAS_PAR_DEGRE:.1f}° "
                  "(mesure fine à l'étape 3)")
        elif vues[H][0] == A and vues[A][0] == H:
            noter(f"  ⚠ {poste} : butées INVERSÉES dans config.py")
            constante_h, constante_a = f"CAP_{poste.upper()}_HORAIRE", f"CAP_{poste.upper()}_ANTIHORAIRE"
            bit_h, bit_a = getattr(cfg, constante_h), getattr(cfg, constante_a)
            corriger(f"{constante_h} = {bit_a}")
            corriger(f"{constante_a} = {bit_h}")
            setattr(cfg, constante_h, bit_a)
            setattr(cfg, constante_a, bit_h)
            E.CABLAGE_BUTEES[(poste, H)], E.CABLAGE_BUTEES[(poste, A)] = bit_a, bit_h
        else:
            noter(f"  ✗ {poste} : la MÊME butée vue dans les deux sens ({vues[H][0]}) — câblage à revoir (test_3)")
            raise SystemExit(1)


# ═══════════════════════════════════════════════════════════════════════════
#  ÉTAPE 3 — REMISE À ZÉRO ET COURSE TOTALE
# ═══════════════════════════════════════════════════════════════════════════

def etape_remise_a_zero(noms: tuple, mesures: int | None = None) -> None:
    """`mesures` None : demandé à l'opérateur. Sinon : initialisation seule (étape 4 directe)."""
    noter("\n  ÉTAPE 3 — REMISE À ZÉRO ET COURSE TOTALE")
    if not confirmer(f"Lancer l'initialisation réelle ({', '.join(noms)}) ?"):
        return
    if mesures is None:
        mesures = nombre("Nombre de mesures", MESURES_PAR_DEFAUT)
    # Plage encore inconnue : tolérance (D9) et budget élargis pour ce test seulement.
    cfg.PLAGE_TOLERANCE_PAS = max(cfg.PLAGE_TOLERANCE_PAS, round(0.9 * min(cfg.PLAGE_NOMINALE_PAS.values())))
    for poste in noms:
        cfg.BUDGET_RECHERCHE_RAPIDE_PAS[poste] = round(cfg.BUDGET_RECHERCHE_RAPIDE_PAS[poste] * 1.5)
    # Le VRAI code des postes, avec nos entrées et nos axes (corrections des étapes 1 et 2).
    postes_p = {nom: Poste(nom, axes[nom], entrees, _commun.CompteursMuets(), buzzer) for nom in noms}
    postes.update(postes_p)
    plages = {poste: [] for poste in noms}
    for numero in range(1, mesures + 1):
        duree = _commun.initialiser(entrees, postes_p, buzzer)
        for poste, p in postes_p.items():
            ecarts = []
            for sens in (A, H):
                rapide = p.detection_rapide.get(sens)
                signe = 1 if sens == H else -1
                ecarts.append("départ sur butée" if rapide is None else
                              f"{signe * (rapide - p.repere_lent[sens]) / cfg.PAS_PAR_DEGRE:+.2f}°")
            plages[poste].append(p.plage)
            noter(f"  ✓ mesure {numero} {poste:5s} : plage {p.plage} pas = {p.degres(p.plage)}, écart "
                  f"rapide/lente A {ecarts[0]}  H {ecarts[1]}  ({duree:.1f} s)")
    for poste, liste in plages.items():
        moyenne = sum(liste) / len(liste)
        dispersion = (max(liste) - min(liste)) / cfg.PAS_PAR_DEGRE
        noter(f"  {poste} : plage moyenne {moyenne / cfg.PAS_PAR_DEGRE:.1f}°, dispersion {dispersion:.2f}°")
        if dispersion > cfg.ECART_RECALAGE_MAX_DEG:
            noter("    ⚠ dispersion importante : perte de pas, jeu mécanique ou galet. À comprendre.")
        if abs(moyenne / cfg.PAS_PAR_DEGRE - cfg.PLAGE_NOMINALE_DEG[poste]) > 0.5:
            corriger(f"PLAGE_NOMINALE_DEG[{poste}] = {moyenne / cfg.PAS_PAR_DEGRE:.1f}   "
                     f"(actuellement {cfg.PLAGE_NOMINALE_DEG[poste]:.1f})")


# ═══════════════════════════════════════════════════════════════════════════
#  ÉTAPE 4 — BOUTONS ROTATION
# ═══════════════════════════════════════════════════════════════════════════

def etape_boutons(noms: tuple) -> None:
    noter("\n  ÉTAPE 4 — BOUTONS ROTATION + / −")
    if not postes or not confirmer("Essayer les boutons ROTATION + / − ?"):
        return
    print("  Maintenir ROTATION + ou − : le mandrin tourne tant que le bouton est tenu.")
    print(f"  Fin automatique après {ESSAI_INACTIVITE_S:.0f} s sans rotation.\n")
    derniere_activite = time.monotonic()
    while time.monotonic() - derniere_activite < ESSAI_INACTIVITE_S:
        maintenant = time.monotonic()
        entrees.rafraichir(maintenant)
        affichage = []
        for nom, poste in postes.items():
            for action in (ROTATION_PLUS, ROTATION_MOINS):
                if entrees.appui(f"{action}_{nom}"):
                    motif = poste.refus(action, maintenant)
                    if motif:
                        print(f"\n    {nom} : refusé — {motif}")
                    else:
                        poste.lancer(action, maintenant)
            poste.avancer(maintenant)
            buzzer.avancer(maintenant)
            if poste.etat == ROTATION:
                derniere_activite = maintenant
            affichage.append(f"{nom} {poste.degres(poste.position):>7s} "
                             f"A{voyant(entrees.butee(nom, A).stable)} H{voyant(entrees.butee(nom, H).stable)}")
        print("\r    " + "    ".join(affichage), end="", flush=True)
        time.sleep(cfg.PERIODE_BOUCLE_S)
    print()
    for nom in postes:
        plus = cfg.SENS_ROTATION_PLUS[nom]
        if confirmer(f"{nom.upper()} : ROTATION + tourne vers {plus.upper()} — est-ce le sens voulu ?"):
            noter(f"  ✓ {nom} : ROTATION + vers {plus}")
        else:
            autre = A if plus == H else H
            noter(f"  ⚠ {nom} : ROTATION + à inverser")
            cfg.SENS_ROTATION_PLUS[nom] = autre
    if cfg.SENS_ROTATION_PLUS != SENS_PLUS_ORIGINE:
        corriger("SENS_ROTATION_PLUS = {POSTE_MERE: SENS_" + cfg.SENS_ROTATION_PLUS[cfg.POSTE_MERE].upper()
                 + ", POSTE_FILLE: SENS_" + cfg.SENS_ROTATION_PLUS[cfg.POSTE_FILLE].upper() + "}")


# ═══════════════════════════════════════════════════════════════════════════

DIR_ORIGINE = dict(cfg.DIR_VERS_HORAIRE)
SENS_PLUS_ORIGINE = dict(cfg.SENS_ROTATION_PLUS)
try:
    depart = menu("Commencer à quelle étape ?", {"1": "identification des moteurs et sens",
                                                 "2": "butées", "3": "remise à zéro et course totale",
                                                 "4": "boutons ROTATION"}, "1")
    noms = _commun.choisir_postes("Postes pour les étapes 2 à 4 ?") if depart != "1" else None
    if depart == "1":
        etape_identification()
        noms = _commun.choisir_postes("Postes pour les étapes 2 à 4 ?")
    construire_axes()
    if depart in ("1", "2"):
        etape_butees(noms)
    etape_remise_a_zero(noms, None if depart != "4" else 1)
    etape_boutons(noms)
except Defaut as defaut:
    noter(f"\n  ✗ DÉFAUT {defaut.code} : {defaut.detail}")
except (TimeoutError, RuntimeError) as erreur:
    noter(f"\n  ✗ {erreur}")
except SystemExit as sortie:
    if sortie.code not in (None, 0, 1):
        noter(str(sortie.code))
except KeyboardInterrupt:
    noter("\n  Interrompu.")
finally:
    _commun.arreter_postes(postes)
    for axe in axes.values():
        axe.demander_arret()
        axe.attendre_fin(cfg.ARRET_THREAD_MAX_S)
    materiel.fermer()
    print("\n  ┌─ RÉCAPITULATIF À M'ENVOYER " + "─" * 46)
    for ligne in journal[1:]:
        if ligne.strip():
            print("  │ " + ligne.strip())
    print("  │")
    print("  │ À recopier dans config.py :" + ("" if corrections else " rien, tout est conforme."))
    for ligne in corrections:
        print("  │ " + ligne)
    print("  └" + "─" * 73)
    _commun.enregistrer(FICHIER, journal + ["", "À recopier dans config.py :"] + corrections)
    print(f"  Enregistré dans : {FICHIER}")
    print("  Moteurs arrêtés et libres, relais à 0.\n")
