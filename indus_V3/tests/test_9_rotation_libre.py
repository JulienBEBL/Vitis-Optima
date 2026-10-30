# -*- coding: utf-8 -*-
"""
test_9_rotation_libre.py — Tourner les mandrins avec les boutons, et régler les mouvements.

⚠ CE TEST FAIT TOURNER LES MOTEURS. Mandrins vides. test_5 (ou test_poste)
   validé d'abord : sens, butées, plage dans config.py.

Lancer depuis Geany (F5). Seuls les moteurs sont pilotés : pas d'électrovanne
(relais à 0 du début à la fin). Le menu demande quels postes sont branchés.

Après l'initialisation réelle (passe rapide, recul, passe lente, centrage), un
menu propose :
  1  TOURNER : ROTATION + / − de chaque poste, maintenus, exactement comme dans le
     programme (rampe de départ, croisière, ralentissement avant la butée, arrêt
     au relâchement ou sur la butée). ACQUITTEMENT = retour au centre. Retour au
     menu après INACTIVITE_S sans rien toucher.
  2  modifier un réglage : vitesses, durée des rampes, zone et vitesse d'approche
     des butées. Pris en compte dès la rotation suivante.
  q  terminer : RÉCAPITULATIF avec les réglages à recopier dans config.py, aussi
     ENREGISTRÉ dans logs/rotation_<date>_<heure>.txt.

config.py n'est jamais modifié par ce test.
"""

import time

import _commun
from _commun import cfg, confirmer, menu, titre, voyant
from libs.entrees import ACQUITTEMENT, ROTATION_MOINS, ROTATION_PLUS
from libs.poste import RECENTRAGE, ROTATION, Defaut

INACTIVITE_S = 60.0
H, A = cfg.SENS_HORAIRE, cfg.SENS_ANTIHORAIRE

FICHIER = _commun.fichier_resultat("rotation")
journal = [f"TEST 9 — rotation libre aux boutons — {time.strftime('%Y-%m-%d %H:%M:%S')}"]


def noter(ligne: str) -> None:
    print(ligne)
    journal.append(ligne.strip("\n"))
    _commun.enregistrer(FICHIER, journal + [""] + _commun.lignes_reglages())


titre("TEST 9 — ROTATION LIBRE AUX BOUTONS")
noms = _commun.choisir_postes("Postes branchés ?")
materiel = _commun.ouvrir(avec_gpio=True)
entrees, postes, buzzer = _commun.construire_postes(materiel, noms)
rotations = {nom: 0 for nom in noms}


def session() -> None:
    """Rotation aux vrais boutons jusqu'à INACTIVITE_S sans rien toucher."""
    print("\n  ROTATION + / − maintenus : le mandrin tourne. ACQUITTEMENT : retour au centre.")
    print(f"  Retour au menu après {INACTIVITE_S:.0f} s sans rien toucher.\n")
    derniere_activite = time.monotonic()
    prochain_affichage = 0.0
    while time.monotonic() - derniere_activite < INACTIVITE_S:
        maintenant = time.monotonic()
        entrees.rafraichir(maintenant)
        for nom, poste in postes.items():
            for action in (ROTATION_PLUS, ROTATION_MOINS):
                if entrees.appui(f"{action}_{nom}"):
                    motif = poste.refus(action, maintenant)
                    if motif:
                        buzzer.bip_refus()
                        print(f"\n    {nom} : refusé — {motif}")
                    else:
                        poste.lancer(action, maintenant)
                        rotations[nom] += 1
        if entrees.appui(ACQUITTEMENT):
            acceptes = [p for p in postes.values() if p.refus_acquittement(maintenant) is None]
            if acceptes:
                buzzer.bip_court()
                for poste in acceptes:
                    poste.acquitter(maintenant)
            else:
                buzzer.bip_refus()
        for poste in postes.values():
            poste.avancer(maintenant)
            if poste.etat in (ROTATION, RECENTRAGE):
                derniere_activite = maintenant
        buzzer.avancer(maintenant)
        if maintenant >= prochain_affichage:        # 20 affichages/s suffisent à l'œil
            prochain_affichage = maintenant + 0.05
            colonnes = [f"{nom[0].upper()} {p.degres(p.position):>7s} {p.etat[:5]:5s} "
                        f"A{voyant(entrees.butee(nom, A).stable)}H{voyant(entrees.butee(nom, H).stable)}"
                        for nom, p in postes.items()]
            print("\r    " + "   ".join(colonnes), end="", flush=True)
        time.sleep(cfg.PERIODE_BOUCLE_S)
    print()
    noter("  session : " + ", ".join(f"{n} {r} rotation(s)" for n, r in rotations.items())
          + " — retard max " + ", ".join(f"{n} {p.axe.retard_max_s * 1000:.1f} ms" for n, p in postes.items()))


try:
    if not confirmer(f"Mandrins vides, zone dégagée : initialiser {', '.join(noms)} ?"):
        raise SystemExit("  Non lancé.")
    duree = _commun.initialiser(entrees, postes, buzzer)
    noter(f"  Initialisés en {duree:.1f} s : "
          + ", ".join(f"{n} plage {p.degres(p.plage)}" for n, p in postes.items()))
    while True:
        _commun.afficher_reglages()
        choix = menu("Que faire ?", {"1": "TOURNER aux boutons", "2": "modifier un réglage",
                                     "q": "terminer"}, "1")
        if choix == "q":
            break
        if choix == "2":
            ligne = _commun.modifier_reglage()
            if ligne:
                noter(f"  réglage : {ligne}")
        else:
            session()
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
    for ligne in journal[1:] + [""] + _commun.lignes_reglages():
        print("  │ " + ligne.strip())
    print("  └" + "─" * 73)
    _commun.enregistrer(FICHIER, journal + [""] + _commun.lignes_reglages())
    print(f"  Enregistré dans : {FICHIER}")
    print("  Moteurs arrêtés et libres, relais à 0.\n")
