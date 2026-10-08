# -*- coding: utf-8 -*-
"""
test_5_moteur.py — Recalage assisté d'un axe, puis auto-test sur les fins de course.

⚠ CE TEST FAIT TOURNER UN MOTEUR. Arrêt d'urgence à portée de main.
   Tests 2 et 3 validés d'abord : l'arrêt dépend des fins de course.

    python3 tests/test_5_moteur.py

PHASE 1 — RECALAGE ASSISTÉ (toi au clavier, très lentement)
  Tu fais tourner l'axe par petits coups, dans un sens ou dans l'autre :
      a = petit coup, DIR à 0        z = petit coup, DIR à 1
      A = grand coup, DIR à 0        Z = grand coup, DIR à 1
      s = état des fins de course    q = quitter
  Chaque coup s'arrête tout seul dès qu'une fin de course de l'axe s'active.
  But : amener l'axe sur une fin de course, puis sur l'autre. Le script note
  avec quel niveau de DIR chaque fin de course a été atteinte, et compte les
  pas entre les deux.

  Au premier coup, vérifier que c'est LE BON AXE qui tourne. Sinon : q, et
  revoir DIR_MERE / DIR_FILLE, ENA_*, PUL_* dans config.py.

PHASE 2 — RÉSULTAT
  Le script en déduit DIR_VERS_COUPE / DIR_VERS_LIGATURAGE et la course
  mesurée, les compare à config.py et affiche les lignes à corriger.

PHASE 3 — AUTO-TEST (lui tout seul, après ton accord)
  Allers-retours entre les deux fins de course, d'abord lents, puis au profil
  (accélération, palier, décélération) si la course mesurée correspond à
  config.py. Il utilise le sens qu'il vient de trouver, même si config.py
  n'est pas encore corrigé. Chaque trajet est borné en pas.

Ctrl+C arrête le moteur à tout moment.
"""

import time

import _commun
from _commun import cfg, confirmer, deplacer, question, titre, voyant
from libs.entrees import Entrees
from libs.moteur import Axe, PortsDrivers

VITESSE_JOG_DEG_S = 10.0     # vitesse des coups manuels, degrés d'axe par seconde
PETIT_COUP_DEG = 2.0
GRAND_COUP_DEG = 15.0
ALLERS_RETOURS_LENTS = 1
ALLERS_RETOURS_PROFIL = 3

COUPE, LIGATURAGE = cfg.POSITION_COUPE, cfg.POSITION_LIGATURAGE

titre("TEST 5 — MOTEUR : RECALAGE ASSISTÉ + AUTO-TEST")
choix = question("Axe à tester : m = mère, f = fille ?")
poste = cfg.POSTE_MERE if choix == "m" else cfg.POSTE_FILLE if choix == "f" else None
if poste is None:
    raise SystemExit("  choix invalide")

materiel = _commun.ouvrir(avec_gpio=True)
drivers = PortsDrivers(materiel.drivers)
entrees = Entrees(materiel.relais, materiel.entrees)
if poste == cfg.POSTE_MERE:
    axe = Axe(poste, materiel.puce, cfg.PUL_MERE, cfg.DIR_MERE, cfg.ENA_MERE, drivers)
else:
    axe = Axe(poste, materiel.puce, cfg.PUL_FILLE, cfg.DIR_FILLE, cfg.ENA_FILLE, drivers)
capteurs = {COUPE: entrees.capteur(poste, COUPE), LIGATURAGE: entrees.capteur(poste, LIGATURAGE)}


def lire_capteurs() -> dict:
    """État stable des deux fins de course de l'axe (anti-rebond rempli)."""
    for _ in range(12):
        entrees.rafraichir(time.monotonic())
        time.sleep(cfg.PERIODE_BOUCLE_S)
    return {position: capteur.stable for position, capteur in capteurs.items()}


def afficher_capteurs(etat: dict) -> None:
    print(f"    fins de course {poste} :  COUPE {voyant(etat[COUPE])}   LIGATURAGE {voyant(etat[LIGATURAGE])}")


def coup(niveau_dir: int, degres: float, actifs_avant: dict) -> tuple:
    """Un coup manuel très lent. S'arrête sur toute fin de course de l'axe qui
    n'était pas active au départ. Renvoie (pas effectués, pas à la détection,
    position atteinte ou None)."""
    nombre = max(1, round(cfg.PAS_PAR_DEGRE * degres))
    axe.preparer(niveau_dir)
    axe.lancer(nombre, lent=True, vitesse_lente_sps=VITESSE_JOG_DEG_S * cfg.PAS_PAR_DEGRE)
    atteinte, pas_detection = None, None
    try:
        while axe.en_marche:
            entrees.rafraichir(time.monotonic())
            if atteinte is None:
                for position, capteur in capteurs.items():
                    if not actifs_avant[position] and capteur.consecutifs >= cfg.CAPTEUR_LECTURES_ARRET:
                        atteinte, pas_detection = position, axe.pas
                        axe.demander_arret_apres(cfg.MOTEUR_SURCOURSE_PAS)
            time.sleep(cfg.PERIODE_BOUCLE_S)
    finally:
        axe.demander_arret()
        axe.attendre_fin(cfg.ARRET_THREAD_MAX_S)
        axe.liberer()
    if axe.erreur is not None:
        raise RuntimeError(f"génération d'impulsions interrompue : {axe.erreur}")
    return axe.pas, pas_detection, atteinte


try:
    # ── PHASE 1 : RECALAGE ASSISTÉ ─────────────────────────────────────────
    etat = lire_capteurs()
    if etat[COUPE] and etat[LIGATURAGE]:
        raise SystemExit("  ⚠ les deux fins de course sont actives (défaut D2) — voir test_3")
    print(f"\n  PHASE 1 — recalage assisté de l'axe {poste.upper()}, à {VITESSE_JOG_DEG_S:.0f}°/s.")
    print(f"    a / z = coup de {PETIT_COUP_DEG:.0f}° (DIR 0 / DIR 1)     "
          f"A / Z = coup de {GRAND_COUP_DEG:.0f}°")
    print("    s = état des fins de course      q = quitter")
    print("  But : atteindre une fin de course, puis l'autre.")
    afficher_capteurs(etat)

    position = 0             # en pas, signée : DIR 1 = +, DIR 0 = −
    trouve = {}              # position → (niveau DIR, position en pas à la détection)
    while len(trouve) < 2:
        commande = input("\n  > ").strip()
        if commande == "q":
            raise SystemExit("  Arrêt demandé.")
        if commande == "s":
            etat = lire_capteurs()
            afficher_capteurs(etat)
            continue
        if commande not in ("a", "z", "A", "Z"):
            print("    touches : a z A Z s q")
            continue
        niveau = 1 if commande in ("z", "Z") else 0
        degres = GRAND_COUP_DEG if commande in ("A", "Z") else PETIT_COUP_DEG

        # Déjà sur une fin de course atteinte dans ce sens : on ne pousse pas plus loin.
        en_butee = [p for p, (n, _) in trouve.items() if n == niveau and etat[p]]
        if en_butee:
            print(f"    refusé : l'axe est déjà sur la fin de course {en_butee[0].upper()} "
                  f"dans ce sens. Repartir dans l'autre sens.")
            continue

        signe = 1 if niveau else -1
        pas, pas_detection, atteinte = coup(niveau, degres, etat)
        if atteinte is not None:
            trouve[atteinte] = (niveau, position + signe * pas_detection)
            print(f"    ✓ fin de course {atteinte.upper()} atteinte avec DIR = {niveau}")
        position += signe * pas
        etat = lire_capteurs()
        print(f"    {pas} pas, DIR = {niveau}, position {position:+d} pas")
        afficher_capteurs(etat)
        if etat[COUPE] and etat[LIGATURAGE]:
            raise SystemExit("  ⚠ les deux fins de course sont actives (défaut D2) — voir test_3")

    # ── PHASE 2 : RÉSULTAT ─────────────────────────────────────────────────
    dir_coupe, pos_coupe = trouve[COUPE]
    dir_ligaturage, pos_ligaturage = trouve[LIGATURAGE]
    course = abs(pos_ligaturage - pos_coupe)
    print("\n  PHASE 2 — résultat")
    if dir_coupe == dir_ligaturage:
        print("  ⚠ Les deux fins de course ont été atteintes avec le MÊME niveau de DIR.")
        print("    Impossible sur un axe qui va et vient : le signal DIR n'arrive pas au")
        print("    driver (DIR_MERE / DIR_FILLE dans config.py, câblage DIR+ / DIR−), ou")
        print("    les deux capteurs sont affectés au même galet.")
        raise SystemExit(1)

    print(f"    DIR_VERS_COUPE      = {dir_coupe}"
          + ("   ✓ comme config.py" if dir_coupe == cfg.DIR_VERS_COUPE else "   ← À CORRIGER dans config.py"))
    print(f"    DIR_VERS_LIGATURAGE = {dir_ligaturage}"
          + ("   ✓ comme config.py" if dir_ligaturage == cfg.DIR_VERS_LIGATURAGE
             else "   ← À CORRIGER dans config.py"))
    degres_mesures = course / cfg.PAS_PAR_DEGRE
    print(f"    course mesurée      = {course} pas = {degres_mesures:.1f}° d'axe "
          f"(config.py : {cfg.MOTEUR_COURSE_PAS} pas = {cfg.MOTEUR_COURSE_DEGRES}°)")
    course_conforme = abs(course - cfg.MOTEUR_COURSE_PAS) <= cfg.MOTEUR_MARGE_PAS
    if not course_conforme:
        print(f"    ← À CORRIGER : MOTEUR_COURSE_DEGRES = {degres_mesures:.1f}")
        print("      (mesure faite à la main, moteur relâché entre les coups : à quelques pas près ;")
        print("       test_6_course.py donne une mesure plus fine)")

    # ── PHASE 3 : AUTO-TEST ────────────────────────────────────────────────
    print("\n  PHASE 3 — auto-test : allers-retours automatiques entre les deux fins de course.")
    if not confirmer("Zone dégagée, lancer l'auto-test ?"):
        raise SystemExit("  Auto-test non lancé.")

    # Le test utilise le sens qu'il vient de trouver, sans attendre la correction de config.py.
    cfg.DIR_VERS_COUPE, cfg.DIR_VERS_LIGATURAGE = dir_coupe, dir_ligaturage
    budget = course + cfg.MOTEUR_MARGE_PAS + cfg.MOTEUR_SURCOURSE_PAS
    cible = COUPE if etat[LIGATURAGE] else LIGATURAGE
    series = [("lent", True, ALLERS_RETOURS_LENTS)]
    if course_conforme:
        series.append(("profil", False, ALLERS_RETOURS_PROFIL))
    else:
        print("    Course mesurée différente de config.py : auto-test LENT seulement.")
        print("    Corriger MOTEUR_COURSE_DEGRES puis relancer pour tester le profil.")

    resultats = []
    detail = {}              # (mode, cible) → [(pas au galet, pas à l'arrêt, durée)]
    for nom, lent, nombre in series:
        if nom == "profil":
            print(f"    profil : {cfg.MOTEUR_VITESSE_MAX_SPS:.0f} pas/s max "
                  f"({cfg.MOTEUR_VITESSE_MAX_SPS / cfg.PAS_PAR_DEGRE:.0f}°/s), approche "
                  f"{cfg.MOTEUR_VITESSE_APPROCHE_SPS:.0f} pas/s")
        for _ in range(2 * nombre):
            debut = time.monotonic()
            pas_capteur, total = deplacer(axe, entrees, poste, cible, lent=lent, budget=budget)
            duree = time.monotonic() - debut
            if pas_capteur is None:
                print(f"    ✗ {nom:6s} vers {cible:11s} : fin de course NON atteinte en {total} pas "
                      "(ce serait un défaut D1)")
                raise SystemExit(1)
            print(f"    ✓ {nom:6s} vers {cible:11s} : galet à {pas_capteur} pas, arrêt à {total} pas, "
                  f"{duree:.2f} s")
            resultats.append(pas_capteur)
            detail.setdefault((nom, cible), []).append((pas_capteur, total, duree))
            cible = COUPE if cible == LIGATURAGE else LIGATURAGE
            time.sleep(0.3)

    ecart = max(resultats) - min(resultats)
    print(f"\n  Auto-test réussi : {len(resultats)} trajets, galet atteint entre {min(resultats)} "
          f"et {max(resultats)} pas (écart {ecart}).")

    print("\n  ┌─ RÉCAPITULATIF À M'ENVOYER " + "─" * 46)
    print(f"  │ axe {poste} — {cfg.DRIVER_PAS_PAR_TOUR} pas/tr, réduction {cfg.MOTEUR_REDUCTION}, "
          f"rampes {'en S' if cfg.MOTEUR_RAMPES_EN_S else 'droites'}")
    print(f"  │ DIR vers coupe = {dir_coupe}, DIR vers ligaturage = {dir_ligaturage}, "
          f"course au recalage manuel = {course} pas")
    print(f"  │ profil : max {cfg.MOTEUR_VITESSE_MAX_SPS:.0f} pas/s, approche "
          f"{cfg.MOTEUR_VITESSE_APPROCHE_SPS:.0f} pas/s, accél. {cfg.MOTEUR_ACCEL_SPS2:.0f}, "
          f"décél. {cfg.MOTEUR_DECEL_SPS2:.0f} pas/s²")
    print("  │")
    print("  │ mode    sens              trajets  pas au galet (min / moy / max)   durée moy.")
    for (nom, sens), mesures in detail.items():
        pas_galet = [m[0] for m in mesures]
        durees = [m[2] for m in mesures]
        print(f"  │ {nom:6s}  vers {sens:11s}  {len(mesures):^7d}  "
              f"{min(pas_galet):5d} / {sum(pas_galet) / len(pas_galet):7.1f} / {max(pas_galet):5d}"
              f"        {sum(durees) / len(durees):5.2f} s")
    print("  └" + "─" * 73)
    if ecart > cfg.MOTEUR_SURCOURSE_PAS + 10:
        print("  ⚠ Écart important entre trajets : perte de pas, jeu mécanique ou galet à")
        print("    grande course morte. À comprendre avant de monter en vitesse.")
except KeyboardInterrupt:
    print("\n  Interrompu.")
finally:
    axe.demander_arret()
    axe.attendre_fin(cfg.ARRET_THREAD_MAX_S)
    materiel.fermer()
    print("  Moteur arrêté et libre, relais à 0.\n")
