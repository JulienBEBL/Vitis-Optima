# -*- coding: utf-8 -*-
"""
test_6_reglage.py — Réglage fin des vitesses et des rampes des moteurs.

⚠ CE TEST FAIT TOURNER LES MOTEURS, jusqu'au décrochage dans les recherches
   automatiques. Arrêt d'urgence à portée de main, mandrins vides.
   test_5_moteur.py validé d'abord (sens, butées, plage dans config.py).

Lancer depuis Geany (F5). Tout se fait au clavier, par un menu ; le programme
se termine par « q ». Rien n'est modifié dans config.py : à la fin, le
RÉCAPITULATIF donne les lignes à recopier ; il est aussi ENREGISTRÉ dans
logs/reglage_<date>_<heure>.txt (réécrit après chaque essai).

Comment on juge un réglage : par l'ÉCART DE RECALAGE. À chaque arrivée sur une
butée, la position comptée en pas est comparée à la butée. Un moteur qui perd
des pas (décrochage au démarrage, à l'arrêt, en croisière) laisse un écart qui
grandit. Quelques centièmes de degré = bon. Au-delà de ECART_RECALAGE_MAX_DEG
(1°) = raté.

Le menu :
  1  modifier un réglage : vitesse de croisière, de démarrage, durée de la rampe,
     vitesse de la passe rapide d'initialisation, vitesse de recentrage
  2  essai ROTATION : allers-retours butée à butée à la vitesse de croisière
     (rampe de départ, arrêt net sur la butée — le mouvement des boutons)
  3  essai RECENTRAGE : retour au centre (rampe de montée ET de descente) puis
     butée horaire pour mesurer l'écart
  4  recherche automatique de la VITESSE MAX : la croisière monte de 25 % à chaque
     palier jusqu'au premier raté ; propose 70 % du dernier palier réussi
  5  recherche automatique de la RAMPE MIN : à la vitesse de la passe rapide, la
     rampe raccourcit de 30 % à chaque palier jusqu'au premier raté ; propose
     1,5 × le dernier palier réussi
  q  terminer
"""

import time

import _commun
from _commun import cfg, confirmer, menu, nombre, titre
from libs import moteur
from libs.poste import PRET, Defaut

H, A = cfg.SENS_HORAIRE, cfg.SENS_ANTIHORAIRE
DELAI_TRAJET_S = 120.0
VITESSE_MAX_RECHERCHE_DEG_S = 90.0   # la recherche automatique ne va jamais au-delà
RAMPE_MIN_RECHERCHE_S = 0.05
MARGE_SECURITE = 0.7                 # vitesse proposée = 70 % de la dernière qui tient

# Réglages modifiables : clé → (libellé, constante en degrés ou secondes, constante en pas/s ou None)
REGLAGES = {
    "1": ("vitesse de croisière (°/s)", "VITESSE_CROISIERE_DEG_S", "VITESSE_CROISIERE_SPS"),
    "2": ("vitesse de démarrage (°/s)", "VITESSE_DEMARRAGE_DEG_S", "VITESSE_DEMARRAGE_SPS"),
    "3": ("durée de la rampe (s)", "DUREE_RAMPE_ROTATION_S", None),
    "4": ("vitesse passe rapide d'init (°/s)", "VITESSE_RECHERCHE_RAPIDE_DEG_S", "VITESSE_RECHERCHE_RAPIDE_SPS"),
    "5": ("vitesse de recentrage (°/s)", "VITESSE_RECENTRAGE_DEG_S", "VITESSE_RECENTRAGE_SPS"),
    "6": ("zone d'approche des butées (°)", "ZONE_APPROCHE_BUTEE_DEG", "ZONE_APPROCHE_BUTEE_PAS"),
    "7": ("vitesse d'approche des butées (°/s)", "VITESSE_APPROCHE_BUTEE_DEG_S", "VITESSE_APPROCHE_BUTEE_SPS"),
}
ORIGINE = {constante: getattr(cfg, constante) for _, constante, _ in REGLAGES.values()}

FICHIER = _commun.fichier_resultat("reglage")
journal = [f"TEST 6 — réglage vitesses et rampes — {time.strftime('%Y-%m-%d %H:%M:%S')}, "
           f"{cfg.DRIVER_PAS_PAR_TOUR} pas/tr, rampes {'en S' if cfg.MOTEUR_RAMPES_EN_S else 'droites'}"]


def noter(ligne: str) -> None:
    print(ligne)
    journal.append(ligne.strip("\n"))
    _commun.enregistrer(FICHIER, journal + [""] + lignes_config())


def lignes_config() -> list:
    lignes = ["À recopier dans config.py :"]
    for _, constante, _ in REGLAGES.values():
        valeur = getattr(cfg, constante)
        marque = "" if valeur == ORIGINE[constante] else f"   (était {ORIGINE[constante]})"
        lignes.append(f"  {constante} = {valeur}{marque}")
    return lignes


def appliquer(constante: str, valeur: float) -> None:
    """Change un réglage pour la suite du test (config.py n'est pas modifié)."""
    for _, deg, sps in REGLAGES.values():
        if deg == constante:
            setattr(cfg, deg, valeur)
            if sps:
                en_pas = valeur * cfg.PAS_PAR_DEGRE
                setattr(cfg, sps, round(en_pas) if sps.endswith("_PAS") else en_pas)
    moteur.vider_cache()                        # les rampes calculées dépendent des réglages


titre("TEST 6 — RÉGLAGE DES VITESSES ET DES RAMPES")
noms = _commun.choisir_postes("Postes à régler ?")
materiel = _commun.ouvrir(avec_gpio=True)
entrees, postes, buzzer = _commun.construire_postes(materiel, noms)


def reinitialiser(liste: list) -> None:
    """Réinitialise les postes donnés (après un raté : la position n'est plus sûre)."""
    _commun.arreter_postes({n: postes[n] for n in liste}, liberer=False)
    _commun.initialiser(entrees, {n: postes[n] for n in liste}, buzzer)


def trajet(sens: str) -> dict:
    """Les postes vers la butée `sens`, ensemble, à la croisière.
    Renvoie poste → (écart en pas, durée, retard max ms), ou le texte du raté."""
    resultats, actifs = {}, {}
    debut = time.monotonic()
    for nom, poste in postes.items():
        if entrees.butee(nom, sens).stable:
            continue                           # déjà sur cette butée : rien à mesurer
        poste.lancer_rotation(sens)
        actifs[nom] = poste
    while actifs:
        try:
            _commun.tourner(entrees, actifs, lambda: any(p.etat == PRET for p in actifs.values()),
                            DELAI_TRAJET_S, f"trajet vers {sens}", buzzer)
        except Defaut as defaut:
            fautif = next((n for n in actifs if defaut.detail.startswith(n)), next(iter(actifs)))
            resultats[fautif] = f"DÉFAUT {defaut.code} : {defaut.detail}"
            _commun.arreter_postes({fautif: actifs.pop(fautif)}, liberer=False)
            continue
        for nom in [n for n, p in actifs.items() if p.etat == PRET]:
            poste = actifs.pop(nom)
            ecart = poste.dernier_ecart_recalage or 0
            if abs(ecart) > cfg.ECART_RECALAGE_MAX_PAS:
                resultats[nom] = f"écart {ecart / cfg.PAS_PAR_DEGRE:+.2f}° (pas perdus)"
            else:
                resultats[nom] = (ecart, time.monotonic() - debut, poste.axe.retard_max_s * 1000)
    return resultats


def serie(nombre_trajets: int, titre_serie: str) -> bool:
    """`nombre_trajets` trajets alternés. Affiche chaque trajet. True si aucun raté."""
    noter(f"\n  {titre_serie}")
    bon = True
    sens = H
    for numero in range(1, nombre_trajets + 1):
        resultats = trajet(sens)
        colonnes = []
        for nom in noms:
            valeur = resultats.get(nom)
            if valeur is None:
                colonnes.append(f"{nom} —")
            elif isinstance(valeur, tuple):
                colonnes.append(f"{nom} {valeur[0] / cfg.PAS_PAR_DEGRE:+.2f}° {valeur[1]:4.1f} s {valeur[2]:4.1f} ms")
            else:
                colonnes.append(f"{nom} ✗ {valeur}")
        noter(f"    {numero:3d} → {sens:12s} " + "   ".join(colonnes))
        rates = [n for n, v in resultats.items() if not isinstance(v, tuple)]
        if rates:
            bon = False
            reinitialiser(rates)
            break
        sens = cfg.sens_oppose(sens)
    return bon


def essai_recentrage(fois: int) -> None:
    noter(f"\n  ESSAI RECENTRAGE à {cfg.VITESSE_RECENTRAGE_DEG_S}°/s, rampe {cfg.DUREE_RAMPE_ROTATION_S} s")
    for numero in range(1, fois + 1):
        maintenant = time.monotonic()
        for poste in postes.values():
            poste.acquitter(maintenant)
        duree = _commun.tourner(entrees, postes, lambda: all(p.etat == PRET for p in postes.values()),
                                DELAI_TRAJET_S, "recentrage", buzzer)
        resultats = trajet(H)
        noter(f"    {numero:3d} : recentrage {duree:4.1f} s, puis butée horaire — "
              + "   ".join(f"{n} " + (f"écart {v[0] / cfg.PAS_PAR_DEGRE:+.2f}°" if isinstance(v, tuple) else f"✗ {v}")
                           for n, v in resultats.items()))
        rates = [n for n, v in resultats.items() if not isinstance(v, tuple)]
        if rates:
            reinitialiser(rates)
            break


def recherche_vitesse_max() -> None:
    depart = cfg.VITESSE_CROISIERE_DEG_S
    vitesse, derniere_bonne = depart, None
    noter(f"\n  RECHERCHE DE LA VITESSE MAX — départ {vitesse:.1f}°/s, rampe {cfg.DUREE_RAMPE_ROTATION_S} s")
    while vitesse <= VITESSE_MAX_RECHERCHE_DEG_S:
        appliquer("VITESSE_CROISIERE_DEG_S", round(vitesse, 1))
        if not serie(2, f"palier {vitesse:.1f}°/s"):
            break
        derniere_bonne = vitesse
        vitesse *= 1.25
    appliquer("VITESSE_CROISIERE_DEG_S", depart)
    if derniere_bonne is None:
        noter("  ✗ Raté dès le premier palier : baisser la croisière ou allonger la rampe (menu 1).")
        return
    proposee = round(derniere_bonne * MARGE_SECURITE, 1)
    noter(f"  Dernier palier réussi : {derniere_bonne:.1f}°/s → vitesse sûre proposée {proposee}°/s (70 %).")
    if confirmer(f"Prendre {proposee}°/s pour la passe rapide d'initialisation ?"):
        appliquer("VITESSE_RECHERCHE_RAPIDE_DEG_S", proposee)
    noter(f"  (croisière laissée à {depart}°/s : c'est un choix de confort pour l'opérateur)")


def recherche_rampe_min() -> None:
    croisiere, rampe = cfg.VITESSE_CROISIERE_DEG_S, cfg.DUREE_RAMPE_ROTATION_S
    vitesse = cfg.VITESSE_RECHERCHE_RAPIDE_DEG_S
    derniere_bonne = None
    noter(f"\n  RECHERCHE DE LA RAMPE MIN — à {vitesse:.1f}°/s (passe rapide), départ {rampe} s")
    appliquer("VITESSE_CROISIERE_DEG_S", vitesse)
    duree = rampe
    while duree >= RAMPE_MIN_RECHERCHE_S:
        appliquer("DUREE_RAMPE_ROTATION_S", round(duree, 2))
        if not serie(2, f"rampe {duree:.2f} s"):
            break
        derniere_bonne = duree
        duree *= 0.7
    appliquer("VITESSE_CROISIERE_DEG_S", croisiere)
    appliquer("DUREE_RAMPE_ROTATION_S", rampe)
    if derniere_bonne is None:
        noter("  ✗ Raté dès le premier palier : la passe rapide est trop rapide pour cette rampe.")
        return
    proposee = round(min(rampe, derniere_bonne * 1.5), 2)
    noter(f"  Rampe la plus courte qui tient : {derniere_bonne:.2f} s → rampe sûre proposée {proposee} s.")
    if confirmer(f"Prendre {proposee} s ?"):
        appliquer("DUREE_RAMPE_ROTATION_S", proposee)


try:
    if not confirmer(f"Mandrins vides, zone dégagée : initialiser {', '.join(noms)} ?"):
        raise SystemExit("  Non lancé.")
    duree = _commun.initialiser(entrees, postes, buzzer)
    noter("  Initialisés en {:.1f} s : ".format(duree)
          + ", ".join(f"{n} plage {p.degres(p.plage)}" for n, p in postes.items()))
    while True:
        print("\n  Réglages actuels :")
        for cle, (libelle, constante, _) in REGLAGES.items():
            print(f"    {libelle:36s} {getattr(cfg, constante)}")
        choix = menu("Que faire ?", {"1": "modifier un réglage", "2": "essai ROTATION (allers-retours)",
                                     "3": "essai RECENTRAGE", "4": "recherche automatique VITESSE MAX",
                                     "5": "recherche automatique RAMPE MIN", "q": "terminer"}, "2")
        if choix == "q":
            break
        if choix == "1":
            cle = menu("Quel réglage ?", {c: libelle for c, (libelle, _, _) in REGLAGES.items()}, "1")
            libelle, constante, _ = REGLAGES[cle]
            texte = input(f"  Nouvelle valeur pour {libelle} [{getattr(cfg, constante)}] ? ").strip()
            try:
                valeur = float(texte.replace(",", ".")) if texte else getattr(cfg, constante)
            except ValueError:
                print("    valeur invalide")
                continue
            if valeur <= 0 or (constante == "VITESSE_DEMARRAGE_DEG_S" and valeur >= cfg.VITESSE_CROISIERE_DEG_S):
                print("    refusé : doit être > 0, et la vitesse de démarrage < la croisière")
                continue
            appliquer(constante, valeur)
            noter(f"  réglage : {constante} = {valeur}")
        elif choix == "2":
            serie(2 * nombre("Nombre d'allers-retours", 5),
                  f"ESSAI ROTATION à {cfg.VITESSE_CROISIERE_DEG_S}°/s, démarrage {cfg.VITESSE_DEMARRAGE_DEG_S}°/s, "
                  f"rampe {cfg.DUREE_RAMPE_ROTATION_S} s — écart / durée / retard max")
        elif choix == "3":
            essai_recentrage(nombre("Nombre de recentrages", 3))
        elif choix == "4":
            if confirmer("Les moteurs vont accélérer jusqu'au décrochage. Continuer ?"):
                recherche_vitesse_max()
        elif choix == "5":
            if confirmer("Les rampes vont raccourcir jusqu'au décrochage. Continuer ?"):
                recherche_rampe_min()
except Defaut as defaut:
    noter(f"\n  ✗ DÉFAUT {defaut.code} : {defaut.detail}")
except TimeoutError as erreur:
    noter(f"\n  ✗ {erreur}")
except KeyboardInterrupt:
    noter("\n  Interrompu.")
finally:
    _commun.arreter_postes(postes)
    materiel.fermer()
    print("\n  ┌─ RÉCAPITULATIF À M'ENVOYER " + "─" * 46)
    for ligne in journal[1:] + [""] + lignes_config():
        print("  │ " + ligne.strip())
    print("  └" + "─" * 73)
    _commun.enregistrer(FICHIER, journal + [""] + lignes_config())
    print(f"  Enregistré dans : {FICHIER}")
    print("  Moteurs arrêtés et libres, relais à 0.\n")
