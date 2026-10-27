# -*- coding: utf-8 -*-
"""
test_5_moteur.py — Un poste : bon moteur, sens de rotation, butées, puis boutons ROTATION ±.

⚠ CE TEST FAIT TOURNER UN MOTEUR. Arrêt d'urgence à portée de main, mandrin
   vide. Tests 2 et 3 validés d'abord : l'arrêt dépend des butées.
⚠ Avant le premier lancement : vérifier les DIP des drivers (6400 pas/tr,
   voir DRIVER_DIP_SWITCH dans config.py).

    python3 tests/test_5_moteur.py

PHASE 1 — COUPS AU CLAVIER (toi, à VITESSE_CROISIERE_DEG_S, sans rampe)
      a = petit coup, DIR à 0        z = petit coup, DIR à 1
      A = grand coup, DIR à 0        Z = grand coup, DIR à 1
      s = état des butées            q = quitter
  Chaque coup s'arrête tout seul dès qu'une butée du poste s'active.
  Au premier coup : vérifier que c'est LE BON MOTEUR qui tourne (sinon q, et
  revoir DIR_* / ENA_* / PUL_*), puis dire dans quel sens le mandrin a tourné,
  VU DU CÔTÉ OPÉRATEUR. But : atteindre une butée, puis l'autre.

PHASE 2 — RÉSULTAT
  DIR_VERS_HORAIRE déduit de ton observation ; vérification que la butée
  atteinte en tournant horaire est bien CAP_*_HORAIRE dans config.py ; plage
  mesurée grossièrement (test_6 la mesure finement).

PHASE 3 — BOUTONS ROTATION + / − (le vrai code du programme)
  Initialisation réelle du poste (deux butées en deux passes, puis centrage),
  puis tu tournes avec les VRAIS boutons ROTATION + et −, maintenus : rampe
  de démarrage, croisière, arrêt au relâchement, arrêt sur butée. La position
  s'affiche en direct. Ctrl+C pour finir, puis dire si ROTATION + tourne dans
  le sens voulu (SENS_ROTATION_PLUS).
  La phase 3 utilise le sens trouvé en phase 2, même si config.py n'est
  pas encore corrigé.

Ctrl+C arrête le moteur à tout moment.
"""

import time

import _commun
from _commun import cfg, confirmer, question, titre, voyant
from libs.entrees import ROTATION_MOINS, ROTATION_PLUS
from libs.poste import ROTATION, Defaut

PETIT_COUP_DEG = 2.0
GRAND_COUP_DEG = 15.0
H, A = cfg.SENS_HORAIRE, cfg.SENS_ANTIHORAIRE

titre("TEST 5 — MOTEUR : SENS, BUTÉES, BOUTONS ROTATION")
choix = question("Poste à tester : m = mère, f = fille ?")
nom = cfg.POSTE_MERE if choix == "m" else cfg.POSTE_FILLE if choix == "f" else None
if nom is None:
    raise SystemExit("  choix invalide")

materiel = _commun.ouvrir(avec_gpio=True)
entrees, postes, buzzer = _commun.construire_postes(materiel, (nom,))
poste = postes[nom]
axe = poste.axe
butees = {H: entrees.butee(nom, H), A: entrees.butee(nom, A)}


def lire_butees() -> dict:
    """État stable des deux butées du poste (anti-rebond rempli)."""
    for _ in range(12):
        entrees.rafraichir(time.monotonic())
        time.sleep(cfg.PERIODE_BOUCLE_S)
    return {sens: butee.stable for sens, butee in butees.items()}


def afficher(etat: dict) -> None:
    print(f"    butées {nom} :  ANTIHORAIRE {voyant(etat[A])}   HORAIRE {voyant(etat[H])}")


def coup(niveau_dir: int, degres: float, actives_avant: dict) -> tuple:
    """Un coup au clavier, vitesse constante. S'arrête sur toute butée qui n'était
    pas active au départ. Renvoie (pas effectués, pas à la détection, butée ou None)."""
    nombre = max(1, round(cfg.PAS_PAR_DEGRE * degres))
    axe.lancer_niveau(niveau_dir, nombre, (), 1.0 / cfg.VITESSE_CROISIERE_SPS)
    atteinte, pas_detection = None, None
    try:
        while axe.en_marche:
            entrees.rafraichir(time.monotonic())
            if atteinte is None:
                for sens, butee in butees.items():
                    if not actives_avant[sens] and butee.consecutifs >= cfg.CAPTEUR_LECTURES_ARRET:
                        atteinte, pas_detection = sens, axe.pas
                        axe.demander_arret()
            time.sleep(cfg.PERIODE_BOUCLE_S)
    finally:
        axe.demander_arret()
        axe.attendre_fin(cfg.ARRET_THREAD_MAX_S)
    if axe.erreur is not None:
        raise RuntimeError(f"génération d'impulsions interrompue : {axe.erreur}")
    return axe.pas, pas_detection, atteinte


try:
    # ── PHASE 1 : COUPS AU CLAVIER ─────────────────────────────────────────
    axe.exciter()
    time.sleep(cfg.MOTEUR_ENA_AVANT_DIR_S)
    etat = lire_butees()
    if etat[H] and etat[A]:
        raise SystemExit("  ⚠ les deux butées sont actives (défaut D2) — voir test_3")
    print(f"\n  PHASE 1 — coups au clavier, poste {nom.upper()}, à {cfg.VITESSE_CROISIERE_DEG_S:.0f}°/s.")
    print(f"    a / z = coup de {PETIT_COUP_DEG:.0f}° (DIR 0 / DIR 1)     "
          f"A / Z = coup de {GRAND_COUP_DEG:.0f}°")
    print("    s = état des butées      q = quitter")
    print("  But : atteindre une butée, puis l'autre.")
    afficher(etat)

    position = 0             # en pas, signée : DIR 1 = +, DIR 0 = −
    trouve = {}              # butée → (niveau DIR, position en pas à la détection)
    dir_horaire_observe = None
    while len(trouve) < 2:
        commande = input("\n  > ").strip()
        if commande == "q":
            raise SystemExit("  Arrêt demandé.")
        if commande == "s":
            etat = lire_butees()
            afficher(etat)
            continue
        if commande not in ("a", "z", "A", "Z"):
            print("    touches : a z A Z s q")
            continue
        niveau = 1 if commande in ("z", "Z") else 0
        degres = GRAND_COUP_DEG if commande in ("A", "Z") else PETIT_COUP_DEG

        # Déjà sur une butée atteinte dans ce sens : on ne pousse pas plus loin.
        en_butee = [s for s, (n, _) in trouve.items() if n == niveau and etat[s]]
        if en_butee:
            print(f"    refusé : le mandrin est déjà sur la butée {en_butee[0].upper()} "
                  "dans ce sens. Repartir dans l'autre sens.")
            continue

        signe = 1 if niveau else -1
        pas, pas_detection, atteinte = coup(niveau, degres, etat)
        if dir_horaire_observe is None and pas > 0:
            reponse = question("Le bon moteur a tourné ? Sens du mandrin vu côté opérateur : "
                               "h = horaire, a = antihoraire, n = mauvais moteur ?")
            if reponse == "n":
                raise SystemExit("  → revoir DIR_MERE / DIR_FILLE, ENA_*, PUL_* dans config.py")
            if reponse in ("h", "a"):
                dir_horaire_observe = niveau if reponse == "h" else 1 - niveau
        if atteinte is not None:
            trouve[atteinte] = (niveau, position + signe * pas_detection)
            print(f"    ✓ butée {atteinte.upper()} atteinte avec DIR = {niveau}")
        position += signe * pas
        etat = lire_butees()
        print(f"    {pas} pas, DIR = {niveau}, position {position:+d} pas")
        afficher(etat)
        if etat[H] and etat[A]:
            raise SystemExit("  ⚠ les deux butées sont actives (défaut D2) — voir test_3")

    # ── PHASE 2 : RÉSULTAT ─────────────────────────────────────────────────
    dir_h, pos_h = trouve[H]
    dir_a, pos_a = trouve[A]
    plage = abs(pos_h - pos_a)
    print("\n  PHASE 2 — résultat")
    if dir_h == dir_a:
        print("  ⚠ Les deux butées ont été atteintes avec le MÊME niveau de DIR.")
        print("    Le signal DIR n'arrive pas au driver (DIR_MERE / DIR_FILLE, câblage DIR+ / DIR−),")
        print("    ou les deux capteurs sont affectés au même galet.")
        raise SystemExit(1)
    if dir_horaire_observe is None:
        dir_horaire_observe = dir_h
        print("    (sens non observé : déduit des butées, en supposant config.py juste)")
    print(f"    DIR_VERS_HORAIRE[{nom}] = {dir_horaire_observe}"
          + ("   ✓ comme config.py" if dir_horaire_observe == cfg.DIR_VERS_HORAIRE[nom]
             else "   ← À CORRIGER dans config.py"))
    if dir_h != dir_horaire_observe:
        print("    ⚠ La butée nommée HORAIRE dans config.py est atteinte en tournant ANTIHORAIRE :")
        print(f"      échanger CAP_{nom.upper()}_HORAIRE et CAP_{nom.upper()}_ANTIHORAIRE dans config.py.")
        print("      Phase 3 impossible tant que ce n'est pas corrigé.")
        raise SystemExit(1)
    print(f"    plage mesurée       = {plage} pas = {plage / cfg.PAS_PAR_DEGRE:.1f}° "
          f"(config.py : {cfg.PLAGE_NOMINALE_DEG[nom]:.1f}°) — mesure fine : test_6")

    # ── PHASE 3 : BOUTONS ROTATION ± ───────────────────────────────────────
    print("\n  PHASE 3 — initialisation réelle du poste, puis essai des boutons ROTATION + / −.")
    if not confirmer("Zone dégagée, lancer l'initialisation ?"):
        raise SystemExit("  Non lancé.")
    # Le test utilise le sens qu'il vient de trouver, sans attendre la correction de config.py.
    cfg.DIR_VERS_HORAIRE[nom], cfg.DIR_VERS_ANTIHORAIRE[nom] = dir_horaire_observe, 1 - dir_horaire_observe
    # Plage pas encore mesurée finement : tolérance élargie pour ce test seulement.
    cfg.PLAGE_TOLERANCE_PAS = max(cfg.PLAGE_TOLERANCE_PAS, round(0.4 * cfg.PLAGE_NOMINALE_PAS[nom]))
    duree = _commun.initialiser(entrees, postes, buzzer)
    print(f"    ✓ initialisé en {duree:.1f} s — plage {poste.degres(poste.plage)}, "
          f"centré à {poste.degres(poste.position)}")

    print("\n  Maintenir ROTATION + ou ROTATION − du poste : le mandrin tourne tant que le")
    print("  bouton est tenu. Ctrl+C pour finir.\n")
    while True:
        try:
            maintenant = time.monotonic()
            entrees.rafraichir(maintenant)
            for action in (ROTATION_PLUS, ROTATION_MOINS):
                if entrees.appui(f"{action}_{nom}"):
                    motif = poste.refus(action, maintenant)
                    if motif:
                        buzzer.bip_refus()
                        print(f"\n    refusé : {motif}")
                    else:
                        poste.lancer(action, maintenant)
            poste.avancer(maintenant)
            buzzer.avancer(maintenant)
            vitesse = "tourne " if poste.etat == ROTATION else "arrêté "
            print(f"\r    {vitesse} position {poste.degres(poste.position):>7s} "
                  f"/ {poste.degres(poste.plage)}   butées A {voyant(butees[A].stable)} "
                  f"H {voyant(butees[H].stable)}   retard max {axe.retard_max_s * 1000:4.1f} ms",
                  end="", flush=True)
            time.sleep(cfg.PERIODE_BOUCLE_S)
        except KeyboardInterrupt:
            break
    _commun.arreter_postes(postes)
    plus = cfg.SENS_ROTATION_PLUS[nom]
    print(f"\n\n  ROTATION + est réglé vers {plus.upper()} (SENS_ROTATION_PLUS[{nom}]).")
    if not confirmer("ROTATION + tourne-t-il dans le sens voulu par l'opérateur ?"):
        print("    → dans config.py, SENS_ROTATION_PLUS : mettre "
              + ("SENS_ANTIHORAIRE" if plus == H else "SENS_HORAIRE") + f" pour {nom}.")
except Defaut as defaut:
    print(f"\n  ✗ DÉFAUT {defaut.code} : {defaut.detail}")
except (TimeoutError, RuntimeError) as erreur:
    print(f"\n  ✗ {erreur}")
except KeyboardInterrupt:
    print("\n  Interrompu.")
finally:
    _commun.arreter_postes(postes)
    materiel.fermer()
    print("  Moteur arrêté et libre, relais à 0.\n")
