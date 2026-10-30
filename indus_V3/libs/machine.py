# -*- coding: utf-8 -*-
"""
machine.py — La boucle des deux postes : entrées, appuis, sorties, défauts du bus.

LOGIQUE.md § 4 à § 6 et § 9.

En V3 les deux postes sont TOTALEMENT INDÉPENDANTS : il n'y a plus de
coordinateur ni de règle entre postes (plus de maître / esclave). Ce module ne
fait que :
  - lire les entrées une fois par tour et faire avancer les deux postes ;
  - transmettre chaque appui au poste concerné, qui l'accepte ou le refuse ;
  - distribuer ACQUITTEMENT, seul bouton commun, aux deux postes ;
  - composer l'octet des relais depuis les deux postes ;
  - traiter les défauts : un défaut de POSTE n'arrête que ce poste ; un défaut
    du BUS (D6) ou d'un MCP (D7), matériel commun, arrête les deux.

Origine : indus V2 libs/machine.py (une lecture par tour, octet composé depuis
l'état, relecture des MCP, chemin de défaut unique), allégé de la coordination.
"""

from __future__ import annotations

import logging

import config as cfg
from libs.entrees import ACQUITTEMENT, ACTIONS, ROTATION_MOINS, ROTATION_PLUS, Entrees
from libs.journal import Compteurs
from libs.materiel import PORT_A, Buzzer, Materiel
from libs.moteur import PortsDrivers
from libs.poste import ATTENTE_ACQUITTEMENT, DEFAUT, DESCRIPTION_DEFAUTS, Defaut, Poste

log = logging.getLogger("vitis")


class Machine:

    def __init__(self, materiel: Materiel, entrees: Entrees, postes: dict[str, Poste],
                 drivers: PortsDrivers, buzzer: Buzzer, compteurs: Compteurs) -> None:
        self._materiel = materiel
        self._entrees = entrees
        self._drivers = drivers
        self._buzzer = buzzer
        self._compteurs = compteurs

        self.postes = postes
        self._bits_ev = {cfg.POSTE_MERE: (cfg.EV_MANDRIN_MERE, cfg.EV_COUPE_MERE),
                         cfg.POSTE_FILLE: (cfg.EV_MANDRIN_FILLE, cfg.EV_COUPE_FILLE)}

        self._prochaine_verif_mcp = 0.0
        self._ecarts_mcp: dict[int, int] = {}   # adresse → relectures fausses consécutives
        self._bus_en_erreur = False

        log.info("En attente d'ACQUITTEMENT pour initialiser les deux postes")

    @property
    def mouvement_en_cours(self) -> bool:
        return any(poste.en_mouvement for poste in self.postes.values())

    # ═══════════════════════════════════════════════════════════════════════
    #  UN TOUR DE BOUCLE  (LOGIQUE.md § 9)
    # ═══════════════════════════════════════════════════════════════════════

    def tour(self, maintenant: float) -> None:
        try:
            self._entrees.rafraichir(maintenant)
            if self._bus_en_erreur:
                log.info("Bus I2C rétabli")
                self._bus_en_erreur = False

            for poste in self.postes.values():
                try:
                    poste.avancer(maintenant)
                except Defaut as defaut:
                    self._declencher_defaut((poste,), defaut.code, defaut.detail)

            self._traiter_boutons(maintenant)
            self._ecrire_sorties()
            self._verifier_mcp(maintenant)

        except Defaut as defaut:
            # Seul D7 remonte jusqu'ici : un MCP est commun aux deux postes.
            self._declencher_defaut(tuple(self.postes.values()), defaut.code, defaut.detail)
        except OSError as erreur:
            # Politique I2C : le driver a déjà retenté I2C_RETRIES fois. Au-delà,
            # c'est un défaut des deux postes. En DÉFAUT, on continue d'essayer à
            # chaque tour (pour lire ACQUITTEMENT), sans inonder le journal.
            vivants = tuple(p for p in self.postes.values() if p.etat != DEFAUT)
            if vivants:
                self._declencher_defaut(tuple(self.postes.values()), "D6", str(erreur))
            elif not self._bus_en_erreur:
                log.error("Bus I2C toujours en erreur : %s", erreur)
            self._bus_en_erreur = True

        self._buzzer.avancer(maintenant)
        self._compteurs.sauver_si_du(maintenant, autorise=not self.mouvement_en_cours)

    # ═══════════════════════════════════════════════════════════════════════
    #  BOUTONS  (les interlocks sont dans le poste)
    # ═══════════════════════════════════════════════════════════════════════

    def _traiter_boutons(self, maintenant: float) -> None:
        if self._entrees.appui(ACQUITTEMENT):
            self._acquitter(maintenant)

        for poste in self.postes.values():
            for action in ACTIONS:
                nom = f"{action}_{poste.nom}"
                if not self._entrees.appui(nom):
                    continue
                motif = poste.refus(action, maintenant)
                if motif:
                    self._refuser(nom, motif)
                    continue
                # Rotation acceptée : pas de bip, il sonnerait à chaque petit coup.
                self._compteurs.bouton(nom, accepte=True)
                if action not in (ROTATION_PLUS, ROTATION_MOINS):
                    self._buzzer.bip_court()
                poste.lancer(action, maintenant)

    def _acquitter(self, maintenant: float) -> None:
        """Un seul bouton pour deux postes : chacun l'exécute s'il le peut."""
        acceptes, motifs = [], []
        for poste in self.postes.values():
            motif = poste.refus_acquittement(maintenant)
            if motif:
                motifs.append(f"{poste.nom} : {motif}")
            else:
                acceptes.append(poste)
        for motif in motifs:
            log.info("Appui %s refusé pour %s", ACQUITTEMENT, motif)
        if not acceptes:
            self._compteurs.bouton(ACQUITTEMENT, accepte=False)
            self._buzzer.bip_refus()
            return
        self._compteurs.bouton(ACQUITTEMENT, accepte=True)
        self._buzzer.bip_court()
        for poste in acceptes:
            poste.acquitter(maintenant)

    def _refuser(self, nom: str, motif: str) -> None:
        self._compteurs.bouton(nom, accepte=False)
        self._buzzer.bip_refus()
        log.info("Appui %s refusé : %s", nom, motif)

    # ═══════════════════════════════════════════════════════════════════════
    #  SORTIES
    # ═══════════════════════════════════════════════════════════════════════

    def _ecrire_sorties(self) -> None:
        """Octet des relais composé depuis les deux postes, écrit seulement s'il change.

        Un poste en attente ou en défaut a ses ev_* à 0 (Poste.neutraliser).
        Une écriture ratée n'a pas mis l'image à jour : elle est retentée au
        tour suivant.
        """
        octet = 0x00
        for poste in self.postes.values():
            bit_mandrin, bit_coupe = self._bits_ev[poste.nom]
            if poste.ev_mandrin:
                octet |= 1 << bit_mandrin
            if poste.ev_coupe:
                octet |= 1 << bit_coupe
        if octet != self._materiel.relais.image(PORT_A):
            self._materiel.relais.ecrire_port(PORT_A, octet)

        # Avant l'initialisation et en défaut, le moteur du poste est libre.
        # Retenté à chaque tour si l'écriture du défaut a échoué.
        for poste in self.postes.values():
            if poste.etat in (ATTENTE_ACQUITTEMENT, DEFAUT) and not poste.axe.libre:
                poste.axe.liberer()

    def _verifier_mcp(self, maintenant: float) -> None:
        """D7 : relecture périodique de la configuration des trois MCP."""
        if maintenant < self._prochaine_verif_mcp:
            return
        self._prochaine_verif_mcp = maintenant + cfg.RELECTURE_CONFIG_MCP_PERIODE_S
        tous_en_defaut = all(p.etat == DEFAUT for p in self.postes.values())
        for mcp in (self._materiel.relais, self._materiel.drivers, self._materiel.entrees):
            ecarts = mcp.ecarts_config()
            if not ecarts:
                self._ecarts_mcp[mcp.adresse] = 0
                continue
            consecutifs = self._ecarts_mcp.get(mcp.adresse, 0) + 1
            self._ecarts_mcp[mcp.adresse] = consecutifs
            # Les deux postes déjà en DÉFAUT : on se contente de reconfigurer, pour
            # continuer à lire ACQUITTEMENT. Un seul avertissement par série.
            if consecutifs >= 2 and not tous_en_defaut:
                raise Defaut("D7", f"MCP 0x{mcp.adresse:02X} : {', '.join(ecarts)}")
            if consecutifs == 1:
                log.warning("MCP 0x%02X : configuration perdue (%s) — reconfiguration",
                            mcp.adresse, ", ".join(ecarts))
            mcp.configurer()

    # ═══════════════════════════════════════════════════════════════════════
    #  DÉFAUT ET ARRÊT
    # ═══════════════════════════════════════════════════════════════════════

    def _declencher_defaut(self, postes: tuple, code: str, detail: str) -> None:
        """Réaction à un défaut (LOGIQUE.md § 6), pour les postes concernés seulement."""
        noms = " + ".join(poste.nom for poste in postes)
        log.error("DÉFAUT %s [%s] — %s : %s", code, noms, DESCRIPTION_DEFAUTS[code], detail)
        for poste in postes:
            poste.neutraliser()
        for poste in postes:
            if not poste.axe.attendre_fin(cfg.ARRET_THREAD_MAX_S):
                log.error("%s : le thread d'impulsions ne s'arrête pas", poste.nom)
        try:
            self._ecrire_sorties()          # relais du ou des postes à 0, moteurs libres
        except OSError as erreur:
            log.error("Sorties non remises en sécurité (%s) — nouvelle tentative à chaque tour", erreur)
        self._buzzer.bip_defaut()
        for poste in postes:
            self._compteurs.defaut(poste.nom, code)
        self._compteurs.sauver()
        log.info("Appuyer sur ACQUITTEMENT pour relancer l'initialisation de %s", noms)

    def arreter(self) -> None:
        """Arrêt du programme : moteurs arrêtés, buzzer coupé, compteurs sauvés.

        Relais et ENA sont remis en sécurité ensuite par Materiel.fermer().
        """
        for poste in self.postes.values():
            poste.neutraliser()
        for poste in self.postes.values():
            if not poste.axe.attendre_fin(cfg.ARRET_THREAD_MAX_S):
                log.error("%s : le thread d'impulsions ne s'arrête pas", poste.nom)
            log.info("%s : retard max des impulsions %.1f ms", poste.nom, poste.axe.retard_max_s * 1000)
        self._buzzer.couper()
        self._compteurs.sauver()
