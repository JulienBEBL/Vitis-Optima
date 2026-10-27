# -*- coding: utf-8 -*-
"""
journal.py — Journal fichier avec rotation, et compteurs persistants.

Origine : Clean-and-Protech V4 logger.py (fichier + console). Changements :
RotatingFileHandler au lieu d'un fichier par lancement, niveau INFO partout
(journal léger : démarrage, initialisation, défauts, changements d'état).

Compteurs (LOGIQUE.md § 11) : un par bouton (acceptés / refusés), un par
actionneur, un par code de défaut. Pas de compteur global. Fichier JSON unique,
écriture atomique.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler

import config as cfg
from libs.entrees import NOMS_BOUTONS
from libs.poste import DESCRIPTION_DEFAUTS

log = logging.getLogger("vitis")

NOMS_ACTIONNEURS = tuple(f"{organe}_{poste}"
                         for poste in cfg.POSTES
                         for organe in ("ev_bridage", "ev_coupe", "moteur"))


def configurer_journal() -> logging.Logger:
    """Fichier tournant + sortie standard (reprise par journalctl sous systemd)."""
    if log.handlers:
        return log
    cfg.CHEMIN_JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    format_ = logging.Formatter("%(asctime)s [%(levelname)-7s] %(message)s", "%Y-%m-%d %H:%M:%S")

    fichier = RotatingFileHandler(cfg.CHEMIN_JOURNAL, maxBytes=cfg.JOURNAL_TAILLE_MAX_OCTETS,
                                  backupCount=cfg.JOURNAL_NB_ARCHIVES, encoding="utf-8")
    fichier.setFormatter(format_)
    # StreamHandler vide son tampon à chaque ligne : sous systemd, la sortie
    # est un tube, et sans cela les lignes arriveraient avec des minutes de retard.
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(format_)

    log.addHandler(fichier)
    log.addHandler(console)
    log.setLevel(logging.INFO)
    log.propagate = False
    return log


def _structure_vide() -> dict:
    return {
        "version": 1,
        "boutons": {nom: {"accepte": 0, "refuse": 0} for nom in NOMS_BOUTONS},
        "actionneurs": {nom: 0 for nom in NOMS_ACTIONNEURS},
        "defauts": {code: 0 for code in DESCRIPTION_DEFAUTS},
    }


class Compteurs:
    """Compteurs en mémoire, recopiés sur disque par écriture atomique.

    L'écriture se fait dans un fichier temporaire, vidé sur disque (fsync), puis
    substitué par os.replace() — atomique sous Linux. Une coupure secteur laisse
    soit l'ancien fichier intact, soit le nouveau complet, jamais un fichier
    tronqué. Aucune exception ne sort d'ici : un compteur ne doit jamais arrêter
    la machine.
    """

    def __init__(self) -> None:
        self._chemin = cfg.CHEMIN_COMPTEURS
        self._donnees = _structure_vide()
        self._modifie = False
        self._prochaine_ecriture = 0.0
        self._charger()

    def _charger(self) -> None:
        if not self._chemin.exists():
            log.info("Compteurs : pas de fichier, départ à zéro (%s)", self._chemin)
            return
        try:
            lu = json.loads(self._chemin.read_text(encoding="utf-8"))
            # Fusion : la structure attendue fait foi, on reprend les valeurs
            # connues. Un compteur ajouté dans une version future part de zéro.
            for nom, valeurs in lu.get("boutons", {}).items():
                if nom in self._donnees["boutons"]:
                    for cle in ("accepte", "refuse"):
                        self._donnees["boutons"][nom][cle] = int(valeurs.get(cle, 0))
            for groupe in ("actionneurs", "defauts"):
                for nom, valeur in lu.get(groupe, {}).items():
                    if nom in self._donnees[groupe]:
                        self._donnees[groupe][nom] = int(valeur)
            log.info("Compteurs chargés (%s)", self._chemin)
        except (OSError, ValueError, TypeError, AttributeError) as erreur:
            copie = self._chemin.with_name(f"{self._chemin.name}.corrompu-{time.strftime('%Y%m%d-%H%M%S')}")
            log.error("Compteurs illisibles (%s) — départ à zéro, fichier conservé sous %s",
                      erreur, copie.name)
            try:
                os.replace(self._chemin, copie)
            except OSError:
                pass
            self._donnees = _structure_vide()

    def bouton(self, nom: str, accepte: bool) -> None:
        self._donnees["boutons"][nom]["accepte" if accepte else "refuse"] += 1
        self._modifie = True

    def actionneur(self, nom: str) -> None:
        self._donnees["actionneurs"][nom] += 1
        self._modifie = True

    def defaut(self, code: str) -> None:
        self._donnees["defauts"][code] += 1
        self._modifie = True

    def sauver(self) -> None:
        if not self._modifie:
            return
        temporaire = self._chemin.with_name(self._chemin.name + ".tmp")
        try:
            self._chemin.parent.mkdir(parents=True, exist_ok=True)
            with open(temporaire, "w", encoding="utf-8") as fichier:
                json.dump(self._donnees, fichier, indent=2, ensure_ascii=False)
                fichier.flush()
                os.fsync(fichier.fileno())
            os.replace(temporaire, self._chemin)
            self._modifie = False
        except OSError as erreur:
            log.error("Compteurs non sauvegardés : %s", erreur)

    def sauver_si_du(self, maintenant: float, autorise: bool) -> None:
        """Sauvegarde périodique. `autorise` = False pendant un mouvement : une
        écriture sur carte SD peut bloquer la boucle ~100 ms."""
        if autorise and maintenant >= self._prochaine_ecriture:
            self._prochaine_ecriture = maintenant + cfg.COMPTEURS_PERIODE_ECRITURE_S
            self.sauver()
