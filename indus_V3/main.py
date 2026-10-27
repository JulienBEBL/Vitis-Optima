#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py — Point d'entrée de la Vitis Optima indus V3.

    Lancement :  python3 main.py
    Arrêt :      Ctrl+C, ou systemctl stop

La logique est décrite dans LOGIQUE.md, les paramètres sont dans config.py.
Ce fichier ne fait que quatre choses :
  1. vérifier config.py et ouvrir le journal ;
  2. ouvrir le matériel en le mettant immédiatement en état sûr
     (relais à 0, ENA des 8 drivers à « libre », PUL à 0) ;
  3. faire tourner la boucle principale à FREQUENCE_BOUCLE_HZ ;
  4. remettre le matériel en état sûr, quelle que soit la cause de l'arrêt
     (Ctrl+C, systemctl stop, exception) — chemin d'arrêt unique, dans le
     `finally`, comme en V1.
"""

import gc
import signal
import sys
import time

import config as cfg
from libs.entrees import Entrees
from libs.journal import Compteurs, configurer_journal
from libs.machine import Machine
from libs.materiel import Buzzer, Materiel
from libs.moteur import Axe, PortsDrivers
from libs.poste import Poste

# Positionné par les gestionnaires de signaux, lu par la boucle principale.
_arret_demande = False


def _handler_arret(sig, _frame):
    """Demande un arrêt propre. Rien d'autre : le travail est fait dans le
    `finally` de main(), pour que le chemin d'arrêt soit unique."""
    global _arret_demande
    _arret_demande = True


def _afficher_config(log):
    log.info("Configuration :")
    log.info("    %d pas/tr (%.2f pas/°), rampes %s de %.1f s",
             cfg.DRIVER_PAS_PAR_TOUR, cfg.PAS_PAR_DEGRE,
             "en S" if cfg.MOTEUR_RAMPES_EN_S else "droites", cfg.DUREE_RAMPE_ROTATION_S)
    log.info("    rotation : démarrage %.1f°/s, croisière %.1f°/s (%.0f pas/s) ; recentrage %.1f°/s",
             cfg.VITESSE_DEMARRAGE_DEG_S, cfg.VITESSE_CROISIERE_DEG_S, cfg.VITESSE_CROISIERE_SPS,
             cfg.VITESSE_RECENTRAGE_DEG_S)
    log.info("    initialisation : passe rapide %.1f°/s, recul %.1f°, passe lente %.1f°/s, "
             "premier sens %s", cfg.VITESSE_RECHERCHE_RAPIDE_DEG_S, cfg.RECUL_CONFIRMATION_DEG,
             cfg.VITESSE_RECHERCHE_LENTE_DEG_S, cfg.INIT_PREMIER_SENS)
    for poste in cfg.POSTES:
        log.info("    %s : plage nominale %.1f° ± %.1f°, DIR vers horaire = %d, ROTATION + = %s",
                 poste, cfg.PLAGE_NOMINALE_DEG[poste], cfg.PLAGE_TOLERANCE_DEG,
                 cfg.DIR_VERS_HORAIRE[poste], cfg.SENS_ROTATION_PLUS[poste])
    log.info("    marge de dépassement %.1f° (tuyau), dégagement max %.1f°",
             cfg.MARGE_DEPASSEMENT_DEG, cfg.DEGAGEMENT_MAX_DEG)
    log.info("    coupe %.2f + %.2f + %.2f s, mandrin %.2f s, garde %.2f s",
             cfg.TEMPS_AVANT_COUPE_S, cfg.TEMPS_COUPE_S, cfg.TEMPS_APRES_COUPE_S,
             cfg.TEMPS_MANOEUVRE_MANDRIN_S, cfg.TEMPS_GARDE_APRES_ACTION_S)
    log.info("    boucle %d Hz", cfg.FREQUENCE_BOUCLE_HZ)


def _construire_machine(materiel: Materiel, compteurs=None) -> Machine:
    """Assemble la machine. `compteurs` : remplacés par les scripts de test."""
    drivers = PortsDrivers(materiel.drivers)
    entrees = Entrees(materiel.relais, materiel.entrees)
    buzzer = Buzzer(materiel.puce)
    if compteurs is None:
        compteurs = Compteurs()
    axes = {
        cfg.POSTE_MERE: Axe(cfg.POSTE_MERE, materiel.puce, cfg.PUL_MERE,
                            cfg.DIR_MERE, cfg.ENA_MERE, drivers),
        cfg.POSTE_FILLE: Axe(cfg.POSTE_FILLE, materiel.puce, cfg.PUL_FILLE,
                             cfg.DIR_FILLE, cfg.ENA_FILLE, drivers),
    }
    postes = {nom: Poste(nom, axes[nom], entrees, compteurs, buzzer) for nom in cfg.POSTES}
    return Machine(materiel, entrees, postes, drivers, buzzer, compteurs)


def _boucle(machine: Machine, log) -> None:
    """Cadence fixe, sans rattrapage : un tour en retard n'est pas rejoué."""
    periode = cfg.PERIODE_BOUCLE_S
    t_suivant = time.monotonic()
    prochain_avertissement = 0.0
    while not _arret_demande:
        machine.tour(time.monotonic())
        t_suivant += periode
        reste = t_suivant - time.monotonic()
        if reste > 0:
            time.sleep(reste)
            continue
        maintenant = time.monotonic()
        if reste < -5 * periode and maintenant >= prochain_avertissement:
            # Un tour lent retarde la lecture des fins de course : à surveiller.
            log.warning("Boucle en retard de %.0f ms", -reste * 1000)
            prochain_avertissement = maintenant + 10.0
        t_suivant = maintenant


def main() -> int:
    signal.signal(signal.SIGINT, _handler_arret)     # Ctrl+C
    signal.signal(signal.SIGTERM, _handler_arret)    # systemctl stop

    try:
        cfg.verifier_config()
    except ValueError as erreur:
        print(f"ERREUR DE CONFIGURATION : {erreur}", file=sys.stderr, flush=True)
        return 2

    log = configurer_journal()
    log.info("═══ Démarrage Vitis Optima indus V3 ═══")
    _afficher_config(log)

    # Les threads d'impulsions doivent récupérer le GIL dès que leur pas arrive
    # à échéance, pas 5 ms plus tard (valeur par défaut de Python).
    sys.setswitchinterval(cfg.PYTHON_SWITCH_INTERVAL_S)

    materiel = Materiel()
    machine = None
    code_retour = 0
    try:
        materiel.ouvrir()
        machine = _construire_machine(materiel)
        # Tous les objets durables existent : on les sort du ramasse-miettes,
        # dont une passe complète pourrait figer les threads d'impulsions.
        gc.freeze()
        _boucle(machine, log)
        log.info("Arrêt demandé")
    except OSError as erreur:
        log.error("ERREUR I2C : %s", erreur)
        log.error("    vérifier SDA/SCL/VDD/GND et les adresses — diagnostic : sudo i2cdetect -y 1")
        code_retour = 1
    except Exception as erreur:                        # noqa: BLE001 — tout doit finir dans le finally
        log.exception("ERREUR INATTENDUE : %r", erreur)
        code_retour = 1
    finally:
        # Chemin d'arrêt unique. Chaque étape est tentée même si la précédente échoue.
        if machine is not None:
            try:
                machine.arreter()
            except Exception as erreur:                # noqa: BLE001
                log.error("Arrêt de la machine incomplet : %r", erreur)
        if materiel.fermer():
            log.info("Relais à 0, moteurs libres")
        else:
            code_retour = 1
        log.info("═══ Arrêt complet ═══")

    return code_retour


if __name__ == "__main__":
    sys.exit(main())
