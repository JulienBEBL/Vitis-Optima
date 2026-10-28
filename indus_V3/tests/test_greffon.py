# -*- coding: utf-8 -*-
"""
test_greffon.py — Mise en service complète du poste GREFFON seul (poste « fille »).

Pour l'étape de montage où un seul moteur et deux butées sont branchés : ceux du
greffon. Le moteur et les butées de l'autre poste peuvent être absents. Les
électrovannes ne sont pas pilotées (relais à 0 du début à la fin).

⚠ CE TEST FAIT TOURNER LE MOTEUR DU GREFFON. Arrêt d'urgence à portée de main,
   mandrin vide. DIP du driver vérifiés (6400 pas/tr, DRIVER_DIP_SWITCH).

Lancer depuis Geany (F5). Tout se fait au clavier, le programme se termine
seul. Chaque étape utilise les corrections trouvées aux étapes précédentes,
même si config.py n'est pas encore corrigé. Un menu permet de reprendre à une
étape.

ÉTAPE 1 — BUTÉES À LA MAIN (moteur arrêté)
  Tu actionnes à la main le galet de la butée HORAIRE (vue côté opérateur),
  puis celui de l'ANTIHORAIRE. Le programme note le bit de chacune et vérifie
  le contact NO. → CAP_* du greffon.
ÉTAPE 2 — MOTEUR
  Petit aller-retour lent (IDENT_DEG). Tu dis si le moteur du greffon a tourné
  et dans quel sens. S'il n'a pas tourné, le programme essaie l'autre driver.
  → correspondance du driver, DIR_VERS_HORAIRE.
ÉTAPE 3 — BUTÉES AU MOTEUR
  Rotation lente vers HORAIRE jusqu'à la butée, puis vers ANTIHORAIRE : la bonne
  butée doit arrêter le moteur. Plage approximative.
ÉTAPE 4 — REMISE À ZÉRO ET COURSE TOTALE
  Initialisation réelle du programme (passe rapide, recul, passe lente de chaque
  côté, centrage), répétée. → PLAGE_NOMINALE_DEG.
ÉTAPE 5 — TOURNER AVEC LES BOUTONS
  ROTATION + / − du greffon, maintenus ; ACQUITTEMENT = retour au centre. La
  position s'affiche. Fin automatique après LIBRE_INACTIVITE_S sans rien toucher.
  → SENS_ROTATION_PLUS.

À la fin : RÉCAPITULATIF avec les lignes à recopier dans config.py, ENREGISTRÉ
dans logs/greffon_<date>_<heure>.txt (réécrit à chaque étape).
"""

import time

import _commun
from _commun import bits, cfg, confirmer, menu, nombre, titre, voyant
from libs import entrees as E
from libs.entrees import ACQUITTEMENT, ROTATION_MOINS, ROTATION_PLUS, Entrees
from libs.materiel import Buzzer
from libs.moteur import Axe, PortsDrivers, periodes_rampe
from libs.poste import PRET, RECENTRAGE, ROTATION, Defaut, Poste

POSTE = cfg.POSTE_FILLE             # le greffon
AUTRE = cfg.POSTE_MERE
IDENT_DEG = 5.0                     # étape 2 : amplitude de l'aller-retour
IDENT_VITESSE_DEG_S = 5.0
BUTEE_VITESSE_DEG_S = 10.0          # étape 3
ATTENTE_GALET_S = 60.0              # étape 1 : attente d'un galet
MESURES_PAR_DEFAUT = 3              # étape 4
LIBRE_INACTIVITE_S = 60.0           # étape 5
H, A = cfg.SENS_HORAIRE, cfg.SENS_ANTIHORAIRE
BITS_BUTEES = range(0, 5)           # 0x26 port B : entrées câblées
# Bit d'ACQUITTEMENT s'il est sur le 0x26 port B : à ne pas prendre pour une butée.
BIT_ACQUITTEMENT_26B = cfg.BTN_ACQUITTEMENT[2] if cfg.BTN_ACQUITTEMENT[:2] == ("0x26", "B") else None

FICHIER = _commun.fichier_resultat("greffon")
corrections = {}        # constante → texte de la ligne config.py
journal = [f"TEST GREFFON — poste « {POSTE} » — {time.strftime('%Y-%m-%d %H:%M:%S')}"]


def lignes_corrections() -> list:
    if not corrections:
        return ["À recopier dans config.py : rien, tout est conforme."]
    return ["À recopier dans config.py :"] + [f"  {ligne}" for ligne in corrections.values()]


def noter(ligne: str) -> None:
    print(ligne)
    journal.append(ligne.strip("\n"))
    _commun.enregistrer(FICHIER, journal + [""] + lignes_corrections())


def corriger(constante: str, ligne: str) -> None:
    corrections[constante] = ligne
    noter(f"    → config.py : {ligne}")


titre("TEST GREFFON — POSTE « FILLE » SEUL")
materiel = _commun.ouvrir(avec_gpio=True)
ports = PortsDrivers(materiel.drivers)
entrees = Entrees(materiel.relais, materiel.entrees)
buzzer = Buzzer(materiel.puce)
etat = {"axe": None, "poste": None}


def butees_greffon() -> list:
    return [(POSTE, H), (POSTE, A)]


def lire_stable() -> None:
    for _ in range(12):
        entrees.rafraichir(time.monotonic())
        time.sleep(cfg.PERIODE_BOUCLE_S)


# ═══════════════════════════════════════════════════════════════════════════
#  ÉTAPE 1 — BUTÉES À LA MAIN
# ═══════════════════════════════════════════════════════════════════════════

def etape_butees_main() -> None:
    noter("\n  ÉTAPE 1 — BUTÉES À LA MAIN (moteur arrêté)")

    def port_b() -> int:
        return materiel.entrees.lire_ports()[1]

    def repos_stable() -> int:
        precedent, identiques = port_b(), 0
        while identiques < 25:
            time.sleep(0.01)
            octet = port_b()
            identiques = identiques + 1 if octet == precedent else 0
            precedent = octet
        return precedent

    print("  Tous les galets LIBRES. Relevé du repos…")
    repos = repos_stable()
    print(f"    0x26 port B au repos : {bits(repos)}")
    trouves = {}
    for sens in (H, A):
        print(f"  → Actionne À LA MAIN le galet de la butée {sens.upper()} du greffon "
              f"(vue côté opérateur), puis relâche … ", end="", flush=True)
        debut, bit = time.monotonic(), None
        while bit is None and time.monotonic() - debut < ATTENTE_GALET_S:
            octet = repos_stable()
            changes = [b for b in BITS_BUTEES if (octet ^ repos) & (1 << b)
                       and b not in trouves.values() and b != BIT_ACQUITTEMENT_26B]
            if len(changes) == 1:
                bit = changes[0]
            elif len(changes) > 1:
                print("\n    ⚠ plusieurs bits ensemble — relâche tout et recommence … ", end="", flush=True)
        if bit is None:
            print("NON VU")
            noter(f"  ✗ butée {sens} : aucun galet vu en {ATTENTE_GALET_S:.0f} s — câblage, ou galet "
                  "inaccessible à la main (l'étape 3 les vérifiera au moteur)")
            return
        niveau = (repos >> bit) & 1
        print(f"GPB{bit} (repos {niveau}, {'NO' if niveau else 'NF ⚠'})")
        trouves[sens] = bit
        while repos_stable() != repos:          # attendre le relâchement
            pass
        if not niveau:
            noter(f"  ⚠ butée {sens} sur GPB{bit} en contact NF : un fil coupé se lirait « en butée »")
    appliquer_butees(trouves[H], trouves[A], "étape 1")


def appliquer_butees(bit_h: int, bit_a: int, origine: str) -> None:
    """Prend les bits trouvés pour le greffon, et range ceux de l'autre poste sur
    les bits restants pour que config.py n'ait jamais deux butées sur un bit."""
    actuel = (getattr(cfg, f"CAP_{POSTE.upper()}_HORAIRE"), getattr(cfg, f"CAP_{POSTE.upper()}_ANTIHORAIRE"))
    if actuel == (bit_h, bit_a):
        noter(f"  ✓ butées du greffon conformes à config.py (horaire GPB{bit_h}, antihoraire GPB{bit_a}) "
              f"[{origine}]")
        return
    noter(f"  ⚠ butées du greffon différentes de config.py : horaire GPB{bit_h}, antihoraire GPB{bit_a} "
          f"[{origine}]")
    libres = [b for b in (1, 2, 3, 4) if b not in (bit_h, bit_a)]
    valeurs = {f"CAP_{POSTE.upper()}_HORAIRE": bit_h, f"CAP_{POSTE.upper()}_ANTIHORAIRE": bit_a,
               f"CAP_{AUTRE.upper()}_HORAIRE": libres[0], f"CAP_{AUTRE.upper()}_ANTIHORAIRE": libres[1]}
    for constante, bit in valeurs.items():
        setattr(cfg, constante, bit)
        suffixe = "   # autre poste : provisoire, non branché" if AUTRE.upper() in constante else ""
        corriger(constante, f"{constante} = {bit}    # GPB{bit}{suffixe}")
    E.CABLAGE_BUTEES[(POSTE, H)], E.CABLAGE_BUTEES[(POSTE, A)] = bit_h, bit_a
    E.CABLAGE_BUTEES[(AUTRE, H)], E.CABLAGE_BUTEES[(AUTRE, A)] = libres[0], libres[1]


# ═══════════════════════════════════════════════════════════════════════════
#  ÉTAPE 2 — MOTEUR
# ═══════════════════════════════════════════════════════════════════════════

def tourner(axe: Axe, niveau_dir: int, pas: int, vitesse_deg_s: float) -> tuple:
    """Rotation à vitesse constante (après la rampe), arrêt au budget ou sur la
    première butée du greffon qui s'active. Renvoie (pas faits, butée vue, pas à la détection)."""
    vitesse = vitesse_deg_s * cfg.PAS_PAR_DEGRE
    lire_stable()
    actives = {cle for cle in butees_greffon() if entrees.butees[cle].stable}
    axe.lancer_niveau(niveau_dir, pas, periodes_rampe(vitesse), 1.0 / vitesse)
    vue, detection = None, None
    try:
        while axe.en_marche:
            entrees.rafraichir(time.monotonic())
            for cle in butees_greffon():
                filtre = entrees.butees[cle]
                if cle in actives and not filtre.brut:
                    actives.discard(cle)
                if vue is None and cle not in actives and filtre.consecutifs >= cfg.CAPTEUR_LECTURES_ARRET:
                    vue, detection = cle[1], axe.pas
                    axe.demander_arret()
            time.sleep(cfg.PERIODE_BOUCLE_S)
    finally:
        axe.demander_arret()
        axe.attendre_fin(cfg.ARRET_THREAD_MAX_S)
    if axe.erreur is not None:
        raise RuntimeError(f"génération d'impulsions interrompue : {axe.erreur}")
    return axe.pas, vue, detection


def driver(nom: str) -> dict:
    return {"PUL": getattr(cfg, f"PUL_{nom.upper()}"), "DIR": getattr(cfg, f"DIR_{nom.upper()}"),
            "ENA": getattr(cfg, f"ENA_{nom.upper()}")}


def construire_axe() -> Axe:
    d = driver(POSTE)
    return Axe(POSTE, materiel.puce, d["PUL"], d["DIR"], d["ENA"], ports)


def etape_moteur() -> None:
    noter("\n  ÉTAPE 2 — MOTEUR")
    print(f"  Le moteur va faire un aller-retour de {IDENT_DEG:.0f}° à {IDENT_VITESSE_DEG_S:.0f}°/s "
          "(arrêt immédiat sur une butée).")
    if not confirmer("Mandrin vide, zone dégagée, lancer ?"):
        raise SystemExit("  Non lancé.")
    pas = round(IDENT_DEG * cfg.PAS_PAR_DEGRE)
    for emplacement in (POSTE, AUTRE):
        d = driver(emplacement)
        axe = Axe(emplacement, materiel.puce, d["PUL"], d["DIR"], d["ENA"], ports)
        axe.exciter()
        time.sleep(cfg.MOTEUR_ENA_AVANT_DIR_S)
        while True:
            print(f"\n  Driver « {emplacement} » de config.py (PUL {d['PUL']}, DIR GPA{d['DIR']}, "
                  f"ENA GPB{d['ENA']}) : aller…", flush=True)
            faits, vue, _ = tourner(axe, 0, pas, IDENT_VITESSE_DEG_S)
            if vue:
                print(f"    (arrêt sur la butée {vue})")
            time.sleep(0.5)
            print("    …retour", flush=True)
            tourner(axe, 1, faits, IDENT_VITESSE_DEG_S)
            reponse = menu("Le moteur du greffon a-t-il tourné ?", {"o": "oui", "n": "non", "r": "recommencer"}, "r")
            if reponse != "r":
                break
        if reponse == "n":
            axe.liberer()
            continue
        sens = menu("À l'ALLER, dans quel sens est parti le mandrin (vu côté opérateur) ?",
                    {"h": "horaire", "a": "antihoraire"}, "h")
        axe.liberer()
        if emplacement != POSTE:
            noter(f"  ⚠ Le greffon est branché sur le driver « {emplacement} » de config.py : drivers à échanger")
            moi, autre = driver(AUTRE), driver(POSTE)
            for nom, valeur in ((f"PUL_{POSTE.upper()}", moi["PUL"]), (f"DIR_{POSTE.upper()}", moi["DIR"]),
                                (f"ENA_{POSTE.upper()}", moi["ENA"]), (f"PUL_{AUTRE.upper()}", autre["PUL"]),
                                (f"DIR_{AUTRE.upper()}", autre["DIR"]), (f"ENA_{AUTRE.upper()}", autre["ENA"])):
                setattr(cfg, nom, valeur)
                corriger(nom, f"{nom} = {valeur}")
        else:
            noter(f"  ✓ Le greffon est sur le driver « {POSTE} » de config.py (PUL {d['PUL']})")
        niveau = 0 if sens == "h" else 1
        if niveau == cfg.DIR_VERS_HORAIRE[POSTE]:
            noter(f"  ✓ sens de rotation conforme (DIR vers horaire = {niveau})")
        else:
            noter("  ⚠ sens de rotation INVERSÉ dans config.py")
            cfg.DIR_VERS_HORAIRE[POSTE], cfg.DIR_VERS_ANTIHORAIRE[POSTE] = niveau, 1 - niveau
            corriger("DIR_VERS_HORAIRE", f"DIR_VERS_HORAIRE = {{POSTE_MERE: {cfg.DIR_VERS_HORAIRE[cfg.POSTE_MERE]}, "
                                         f"POSTE_FILLE: {cfg.DIR_VERS_HORAIRE[cfg.POSTE_FILLE]}}}")
        etat["axe"] = construire_axe()
        return
    noter("  ✗ Le moteur n'a tourné sur aucun des deux drivers : alimentation, LED rouge du driver, "
          "câble moteur, ENA, DIP.")
    raise SystemExit(1)


# ═══════════════════════════════════════════════════════════════════════════
#  ÉTAPE 3 — BUTÉES AU MOTEUR
# ═══════════════════════════════════════════════════════════════════════════

def etape_butees_moteur() -> None:
    noter("\n  ÉTAPE 3 — BUTÉES AU MOTEUR")
    axe = etat["axe"] or construire_axe()
    etat["axe"] = axe
    budget = round(cfg.PLAGE_NOMINALE_DEG[POSTE] * 1.5 * cfg.PAS_PAR_DEGRE)
    print(f"  Rotation à {BUTEE_VITESSE_DEG_S:.0f}°/s vers HORAIRE puis ANTIHORAIRE, "
          f"{budget / cfg.PAS_PAR_DEGRE:.0f}° au plus par trajet.")
    if not confirmer("Lancer ?"):
        return
    axe.exciter()
    time.sleep(cfg.MOTEUR_ENA_AVANT_DIR_S)
    vues = {}
    for sens in (H, A):
        niveau = (cfg.DIR_VERS_HORAIRE if sens == H else cfg.DIR_VERS_ANTIHORAIRE)[POSTE]
        print(f"    → {sens}…", end="", flush=True)
        faits, vue, detection = tourner(axe, niveau, budget, BUTEE_VITESSE_DEG_S)
        if vue is None:
            print(" rien")
            noter(f"  ✗ aucune butée vue en tournant {sens} sur {faits / cfg.PAS_PAR_DEGRE:.0f}° — capteur "
                  "débranché ou mort, ou sens de rotation faux (étape 2)")
            raise SystemExit(1)
        print(f" butée « {vue} » de config.py après {detection / cfg.PAS_PAR_DEGRE:.1f}°")
        vues[sens] = (vue, detection)
        time.sleep(0.5)
    if vues[H][0] == H and vues[A][0] == A:
        noter(f"  ✓ la bonne butée arrête le moteur dans chaque sens ; plage ≈ "
              f"{vues[A][1] / cfg.PAS_PAR_DEGRE:.1f}° (mesure fine à l'étape 4)")
    elif vues[H][0] == A and vues[A][0] == H:
        noter("  ⚠ butées inversées par rapport au sens du moteur")
        appliquer_butees(getattr(cfg, f"CAP_{POSTE.upper()}_ANTIHORAIRE"),
                         getattr(cfg, f"CAP_{POSTE.upper()}_HORAIRE"), "étape 3")
    else:
        noter(f"  ✗ la même butée ({vues[H][0]}) vue dans les deux sens — câblage à revoir")
        raise SystemExit(1)


# ═══════════════════════════════════════════════════════════════════════════
#  ÉTAPE 4 — REMISE À ZÉRO ET COURSE TOTALE
# ═══════════════════════════════════════════════════════════════════════════

def construire_poste() -> Poste:
    if etat["poste"] is None:
        etat["axe"] = etat["axe"] or construire_axe()
        etat["poste"] = Poste(POSTE, etat["axe"], entrees, _commun.CompteursMuets(), buzzer)
    return etat["poste"]


def etape_course(mesures: int | None = None) -> None:
    noter("\n  ÉTAPE 4 — REMISE À ZÉRO ET COURSE TOTALE")
    if not confirmer("Lancer l'initialisation réelle du greffon ?"):
        return
    if mesures is None:
        mesures = nombre("Nombre de mesures", MESURES_PAR_DEFAUT)
    # Plage encore incertaine : tolérance (D9) et budget élargis pour ce test.
    cfg.PLAGE_TOLERANCE_PAS = max(cfg.PLAGE_TOLERANCE_PAS, round(0.9 * cfg.PLAGE_NOMINALE_PAS[POSTE]))
    cfg.BUDGET_RECHERCHE_RAPIDE_PAS[POSTE] = round(cfg.BUDGET_RECHERCHE_RAPIDE_PAS[POSTE] * 1.5)
    poste = construire_poste()
    plages = []
    for numero in range(1, mesures + 1):
        duree = _commun.initialiser(entrees, {POSTE: poste}, buzzer)
        ecarts = []
        for sens in (A, H):
            rapide = poste.detection_rapide.get(sens)
            signe = 1 if sens == H else -1
            ecarts.append("départ sur butée" if rapide is None else
                          f"{signe * (rapide - poste.repere_lent[sens]) / cfg.PAS_PAR_DEGRE:+.2f}°")
        plages.append(poste.plage)
        noter(f"  ✓ mesure {numero} : plage {poste.plage} pas = {poste.degres(poste.plage)}, écart "
              f"rapide/lente A {ecarts[0]}  H {ecarts[1]}  ({duree:.1f} s)")
    moyenne = sum(plages) / len(plages)
    dispersion = (max(plages) - min(plages)) / cfg.PAS_PAR_DEGRE
    noter(f"  plage moyenne {moyenne / cfg.PAS_PAR_DEGRE:.1f}°, dispersion {dispersion:.2f}°")
    if dispersion > cfg.ECART_RECALAGE_MAX_DEG:
        noter("    ⚠ dispersion importante : perte de pas, jeu mécanique ou galet. À comprendre.")
    if abs(moyenne / cfg.PAS_PAR_DEGRE - cfg.PLAGE_NOMINALE_DEG[POSTE]) > 0.5:
        cfg.PLAGE_NOMINALE_DEG[POSTE] = round(moyenne / cfg.PAS_PAR_DEGRE, 1)
        corriger("PLAGE_NOMINALE_DEG", f"PLAGE_NOMINALE_DEG = {{POSTE_MERE: {cfg.PLAGE_NOMINALE_DEG[cfg.POSTE_MERE]}, "
                                       f"POSTE_FILLE: {cfg.PLAGE_NOMINALE_DEG[cfg.POSTE_FILLE]}}}")


# ═══════════════════════════════════════════════════════════════════════════
#  ÉTAPE 5 — TOURNER AVEC LES BOUTONS
# ═══════════════════════════════════════════════════════════════════════════

def etape_boutons() -> None:
    noter("\n  ÉTAPE 5 — TOURNER AVEC LES BOUTONS")
    poste = construire_poste()
    if poste.etat != PRET:
        print("  Le greffon doit d'abord être initialisé.")
        etape_course(1)
        if poste.etat != PRET:
            return
    print("  ROTATION + / − du greffon, maintenus : le mandrin tourne. ACQUITTEMENT : retour au centre.")
    print(f"  Fin automatique après {LIBRE_INACTIVITE_S:.0f} s sans rien toucher.\n")
    rotations, derniere_activite = 0, time.monotonic()
    while time.monotonic() - derniere_activite < LIBRE_INACTIVITE_S:
        maintenant = time.monotonic()
        entrees.rafraichir(maintenant)
        for action in (ROTATION_PLUS, ROTATION_MOINS):
            if entrees.appui(f"{action}_{POSTE}"):
                motif = poste.refus(action, maintenant)
                if motif:
                    buzzer.bip_refus()
                    print(f"\n    refusé — {motif}")
                else:
                    poste.lancer(action, maintenant)
                    rotations += 1
        if entrees.appui(ACQUITTEMENT):
            motif = poste.refus_acquittement(maintenant)
            if motif:
                buzzer.bip_refus()
                print(f"\n    ACQUITTEMENT refusé — {motif}")
            else:
                buzzer.bip_court()
                poste.acquitter(maintenant)
        poste.avancer(maintenant)
        buzzer.avancer(maintenant)
        if poste.etat in (ROTATION, RECENTRAGE):
            derniere_activite = maintenant
        print(f"\r    {poste.etat:10s} position {poste.degres(poste.position):>7s} / {poste.degres(poste.plage)}"
              f"   A {voyant(entrees.butee(POSTE, A).stable)}  H {voyant(entrees.butee(POSTE, H).stable)}"
              f"   retard {poste.axe.retard_max_s * 1000:4.1f} ms", end="", flush=True)
        time.sleep(cfg.PERIODE_BOUCLE_S)
    print()
    noter(f"  {rotations} rotation(s) aux boutons")
    if rotations:
        plus = cfg.SENS_ROTATION_PLUS[POSTE]
        if confirmer(f"ROTATION + tourne vers {plus.upper()} — est-ce le sens voulu ?"):
            noter(f"  ✓ ROTATION + vers {plus}")
        else:
            cfg.SENS_ROTATION_PLUS[POSTE] = A if plus == H else H
            noter("  ⚠ ROTATION + à inverser")
            corriger("SENS_ROTATION_PLUS",
                     "SENS_ROTATION_PLUS = {POSTE_MERE: SENS_" + cfg.SENS_ROTATION_PLUS[cfg.POSTE_MERE].upper()
                     + ", POSTE_FILLE: SENS_" + cfg.SENS_ROTATION_PLUS[cfg.POSTE_FILLE].upper() + "}")


# ═══════════════════════════════════════════════════════════════════════════

ETAPES = {"1": etape_butees_main, "2": etape_moteur, "3": etape_butees_moteur, "4": etape_course,
          "5": etape_boutons}
try:
    depart = menu("Commencer à quelle étape ?", {"1": "butées à la main", "2": "moteur (quel driver, sens)",
                                                 "3": "butées au moteur", "4": "remise à zéro et course totale",
                                                 "5": "tourner avec les boutons"}, "1")
    for cle in sorted(ETAPES):
        if cle >= depart:
            ETAPES[cle]()
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
    if etat["poste"] is not None:
        _commun.arreter_postes({POSTE: etat["poste"]})
    elif etat["axe"] is not None:
        etat["axe"].demander_arret()
        etat["axe"].attendre_fin(cfg.ARRET_THREAD_MAX_S)
    materiel.fermer()
    print("\n  ┌─ RÉCAPITULATIF À M'ENVOYER " + "─" * 46)
    for ligne in journal[1:] + [""] + lignes_corrections():
        if ligne.strip() or ligne == "":
            print("  │ " + ligne.strip())
    print("  └" + "─" * 73)
    _commun.enregistrer(FICHIER, journal + [""] + lignes_corrections())
    print(f"  Enregistré dans : {FICHIER}")
    print("  Moteur arrêté et libre, relais à 0.\n")
