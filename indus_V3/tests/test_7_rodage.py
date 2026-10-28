# -*- coding: utf-8 -*-
"""
test_7_rodage.py — Allers-retours des DEUX mandrins, butée à butée, en même temps.

⚠ CE TEST FAIT TOURNER LES DEUX MOTEURS EN MÊME TEMPS. Arrêt d'urgence à portée
   de main, mandrins vides. test_5 et test_6 validés sur les deux postes d'abord.

    python3 tests/test_7_rodage.py

Déroulé, avec le VRAI code des postes (libs/poste.py) :
  1. initialisation réelle des deux postes, en même temps (deux butées en deux
     passes, puis centrage) ;
  2. après ton accord, les deux mandrins partent ENSEMBLE vers leur butée
     HORAIRE à la vitesse de croisière (rampe de démarrage comprise) ; chacun
     s'arrête sur sa butée ; le script attend que LES DEUX soient arrivés ;
  3. puis vers ANTIHORAIRE ; et ainsi de suite.

À chaque arrivée, la position comptée en pas est comparée à la butée : c'est
l'« écart de recalage ». Il doit rester de quelques pas. S'il grandit, le
moteur perd des pas (décrochage, rampe trop courte, courant trop faible).

UN DÉFAUT N'ARRÊTE PAS LE RODAGE. Le script note le raté, réinitialise le poste
concerné, puis continue. Il ne s'arrête que si RATES_DE_SUITE_MAX trajets ratés
se suivent.

POUR ARRÊTER AVANT LA FIN : appuyer sur ACQUITTEMENT. Le rodage s'arrête à la
fin du trajet en cours, proprement. (Dans Geany, Ctrl+C ferme la fenêtre : le
garder pour l'urgence, avec l'arrêt d'urgence.)

À la fin : récapitulatif par poste et par sens, à m'envoyer.
Il est aussi ENREGISTRÉ dans indus_V3/logs/rodage_<date>_<heure>.txt, et
réécrit tous les 20 trajets et à chaque raté.

Colonne « retard » : pire retard d'une impulsion pendant le trajet, en ms. Les
deux moteurs tournant ensemble, c'est l'indicateur à surveiller : un retard de
plusieurs ms juste avant un raté désignerait la génération des impulsions
(Python, système) plutôt que la mécanique.
"""

import time
from pathlib import Path

import _commun
from _commun import cfg, confirmer, question, titre
from libs.entrees import ACQUITTEMENT
from libs.poste import PRET, Defaut

PAUSE_ENTRE_TRAJETS_S = 0.5
RATES_DE_SUITE_MAX = 3
ENREGISTREMENT_TOUS_LES = 20
FICHIER_RECAP = Path(cfg.CHEMIN_JOURNAL).parent / f"rodage_{time.strftime('%Y%m%d_%H%M%S')}.txt"
CYCLES_PAR_DEFAUT = 10
DELAI_TRAJET_S = 60.0

titre("TEST 7 — RODAGE : ALLERS-RETOURS DES DEUX MANDRINS ENSEMBLE")
print("  ⚠ Les deux moteurs tournent en même temps. Mandrins vides.")
reponse = question(f"Nombre d'allers-retours [{CYCLES_PAR_DEFAUT}] ?")
cycles = int(reponse) if reponse.isdigit() and int(reponse) > 0 else CYCLES_PAR_DEFAUT

materiel = _commun.ouvrir(avec_gpio=True)
entrees, postes, buzzer = _commun.construire_postes(materiel)
mesures = {}       # (poste, sens) → [(écart de recalage en pas, durée, retard max ms)]
rates = {}         # (poste, sens) → [(numéro du trajet, raison)]
plages = {}        # poste → plage mesurée à la dernière initialisation (pas)
arret_demande = [False]   # ACQUITTEMENT appuyé pendant le rodage


def surveiller_acquittement() -> bool:
    """Appelé à chaque tour de boucle : note un appui sur ACQUITTEMENT."""
    if entrees.appui(ACQUITTEMENT) and not arret_demande[0]:
        arret_demande[0] = True
        buzzer.bip_court()
        print("\n        ACQUITTEMENT : arrêt à la fin du trajet en cours")
    return False


def trajet(sens: str) -> dict:
    """Les deux mandrins vers la butée `sens`, ensemble. Renvoie poste → mesure ou raison du raté."""
    resultats = {}
    actifs = {}
    debut = time.monotonic()
    for nom, poste in postes.items():
        if poste.etat != PRET:
            resultats[nom] = "poste non initialisé"
        elif entrees.butee(nom, sens).stable:
            resultats[nom] = f"déjà sur la butée {sens}"
        else:
            poste.lancer_rotation(sens)
            actifs[nom] = poste
    while actifs:
        try:
            _commun.tourner(entrees, actifs,
                            lambda: surveiller_acquittement() or any(p.etat == PRET for p in actifs.values()),
                            DELAI_TRAJET_S, f"trajet vers {sens}", buzzer)
        except Defaut as defaut:
            fautif = _poste_du_defaut(defaut, actifs)
            resultats[fautif] = f"DÉFAUT {defaut.code} : {defaut.detail}"
            _commun.arreter_postes({fautif: actifs.pop(fautif)})
            continue
        except TimeoutError as erreur:
            for nom in list(actifs):
                resultats[nom] = str(erreur)
            _commun.arreter_postes(actifs)
            break
        for nom in [n for n, p in actifs.items() if p.etat == PRET]:
            poste = actifs.pop(nom)
            resultats[nom] = (poste.dernier_ecart_recalage or 0, time.monotonic() - debut,
                              poste.axe.retard_max_s * 1000)
    return resultats


def _poste_du_defaut(defaut: Defaut, actifs: dict) -> str:
    """Le message d'un défaut de poste commence par le nom du poste."""
    for nom in actifs:
        if defaut.detail.startswith(nom):
            return nom
    return next(iter(actifs))


def recapitulatif(faits: int, afficher: bool = True) -> None:
    lignes = ["┌─ RÉCAPITULATIF À M'ENVOYER " + "─" * 58]
    lignes.append(f"│ {time.strftime('%Y-%m-%d %H:%M:%S')} — {faits} trajet(s), {cfg.DRIVER_PAS_PAR_TOUR} pas/tr, "
                  f"croisière {cfg.VITESSE_CROISIERE_DEG_S:.1f}°/s, démarrage {cfg.VITESSE_DEMARRAGE_DEG_S:.1f}°/s, "
                  f"rampe {cfg.DUREE_RAMPE_ROTATION_S:.1f} s {'en S' if cfg.MOTEUR_RAMPES_EN_S else 'droite'}")
    for nom, poste in postes.items():
        lignes.append(f"│ {nom:5s} : plage mesurée {poste.degres(plages.get(nom))} "
                      f"(nominale {cfg.PLAGE_NOMINALE_DEG[nom]:.1f}°)")
    lignes.append("│")
    lignes.append("│ poste  sens          réussis  ratés  écart de recalage (min / moy / max)   durée moy.   retard max")
    for cle in sorted(set(mesures) | set(rates)):
        nom, sens = cle
        liste = mesures.get(cle, [])
        if liste:
            ecarts = [m[0] / cfg.PAS_PAR_DEGRE for m in liste]
            durees = [m[1] for m in liste]
            chiffres = (f"{min(ecarts):+6.2f}° / {sum(ecarts) / len(ecarts):+6.2f}° / {max(ecarts):+6.2f}°"
                        f"      {sum(durees) / len(durees):5.1f} s     {max(m[2] for m in liste):5.1f} ms")
        else:
            chiffres = "    —"
        lignes.append(f"│ {nom:5s}  {sens:12s}  {len(liste):^7d}  {len(rates.get(cle, [])):^5d}  {chiffres}")
    total = sum(len(liste) for liste in rates.values())
    lignes.append("│")
    lignes.append(f"│ ratés : {total}")
    for (nom, sens), liste in sorted(rates.items()):
        for numero, raison in liste:
            lignes.append(f"│   trajet {numero:4d} — {nom} vers {sens} : {raison}")
    lignes.append("└" + "─" * 86)
    try:
        FICHIER_RECAP.parent.mkdir(parents=True, exist_ok=True)
        FICHIER_RECAP.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    except OSError as erreur:
        print(f"  (récapitulatif non enregistré : {erreur})")
    if afficher:
        print()
        for ligne in lignes:
            print("  " + ligne)
        print(f"  Enregistré dans : {FICHIER_RECAP}")


faits = 0
try:
    print("\n  Initialisation des deux postes (en même temps)…")
    duree = _commun.initialiser(entrees, postes, buzzer)
    for nom, poste in postes.items():
        plages[nom] = poste.plage
        print(f"    {nom:5s} : plage {poste.degres(poste.plage)}, centré à {poste.degres(poste.position)}")
    print(f"  Initialisés en {duree:.1f} s.")

    if not confirmer(f"Lancer {cycles} allers-retours des deux mandrins ensemble ?"):
        raise SystemExit("  Non lancé.")

    print(f"  Récapitulatif enregistré au fil de l'eau dans : {FICHIER_RECAP}")
    print("  Pour arrêter avant la fin : ACQUITTEMENT (arrêt à la fin du trajet en cours).")
    print("\n   n°  vers          mère : écart / durée / retard       fille : écart / durée / retard")

    def colonne(valeur) -> str:
        if not isinstance(valeur, tuple):
            return "         R A T É          "
        return f"{valeur[0] / cfg.PAS_PAR_DEGRE:+6.2f}° / {valeur[1]:5.1f} s / {valeur[2]:4.1f} ms"

    sens = cfg.SENS_HORAIRE
    rates_de_suite = 0
    for numero in range(1, 2 * cycles + 1):
        resultats = trajet(sens)
        faits += 1
        echecs = {n: r for n, r in resultats.items() if not isinstance(r, tuple)}
        for nom, valeur in resultats.items():
            if isinstance(valeur, tuple):
                mesures.setdefault((nom, sens), []).append(valeur)
        print(f"  {numero:4d}  {sens:12s}  {colonne(resultats.get(cfg.POSTE_MERE))}"
              f"     {colonne(resultats.get(cfg.POSTE_FILLE))}")
        if echecs:
            for nom, raison in echecs.items():
                rates.setdefault((nom, sens), []).append((numero, raison))
                print(f"        ✗ raté — {nom} : {raison}")
            rates_de_suite += 1
            recapitulatif(faits, afficher=False)
            if rates_de_suite >= RATES_DE_SUITE_MAX:
                raise SystemExit(f"  ✗ ARRÊT : {RATES_DE_SUITE_MAX} trajets ratés de suite — rodage arrêté")
            print("        réinitialisation du ou des postes en raté, puis reprise :")
            _commun.initialiser(entrees, {n: postes[n] for n in echecs}, buzzer)
            plages.update({n: postes[n].plage for n in echecs})
        else:
            rates_de_suite = 0
        sens = cfg.sens_oppose(sens)
        if numero % ENREGISTREMENT_TOUS_LES == 0:
            recapitulatif(faits, afficher=False)
        if arret_demande[0]:
            break
        time.sleep(PAUSE_ENTRE_TRAJETS_S)
    total = sum(len(liste) for liste in rates.values())
    fin = "arrêté par ACQUITTEMENT" if arret_demande[0] else "terminé"
    print(f"\n  Rodage {fin} : {faits} trajets, {total} raté(s).")
except Defaut as defaut:
    print(f"\n  ✗ DÉFAUT {defaut.code} : {defaut.detail}")
except TimeoutError as erreur:
    print(f"\n  ✗ {erreur}")
except KeyboardInterrupt:
    print("\n  Interrompu.")
finally:
    _commun.arreter_postes(postes)
    materiel.fermer()
    if mesures or rates:
        recapitulatif(faits)
    print("  Moteurs arrêtés et libres, relais à 0.\n")
