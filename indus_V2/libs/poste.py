# -*- coding: utf-8 -*-
"""
poste.py — Machine à états d'un poste (mère ou fille). LOGIQUE.md § 3.2 et § 4.2.

Un poste possède son bridage, sa coupe et son axe. Il applique ses propres
interlocks (I2 à I6) et détecte ses propres défauts (D1 à D5, D8). Il ne
connaît NI l'autre poste, NI l'état global : c'est le coordinateur (machine.py)
qui décide si une demande est autorisée, puis qui appelle lancer_*().

Règle centrale (LOGIQUE.md § 2.2) : une commande d'actionneur n'est jamais
instantanée. Chaque action a une durée ; l'état de l'actionneur (bridé,
position) ne change qu'à la FIN de l'action ; pendant l'action le poste est
occupé et ses boutons sont refusés. La variable ne peut jamais être en avance
sur le vérin.

Le poste n'écrit AUCUNE sortie relais : il expose ev_bridage et ev_coupe, et le
coordinateur compose l'octet du port. Seul l'axe (ENA / DIR) est piloté d'ici.

Origine : Vitis V1 indus/vitis_optima.py, classe `Machine` (actions gardées,
échéance non bloquante de `surveiller_coupe()`), réécrite en machine à états.
"""

from __future__ import annotations

import logging

import config as cfg
from libs.entrees import Filtre
from libs.moteur import Axe

log = logging.getLogger("vitis")


class Defaut(Exception):
    """Défaut machine. Levé n'importe où, traité en un seul endroit par le coordinateur."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code} — {detail}")
        self.code = code
        self.detail = detail


DESCRIPTION_DEFAUTS = {
    "D1": "fin de course cible non atteinte (budget de pas épuisé)",
    "D2": "deux fins de course actives sur le même axe",
    "D3": "fin de course cible déjà active au départ",
    "D4": "fin de course de départ toujours active : le moteur ne tourne pas",
    "D5": "fin de course perdue à l'arrêt, ou non confirmée à l'arrivée",
    "D6": "erreur de bus I2C",
    "D7": "configuration d'un MCP23017 perdue",
    "D8": "initialisation : position coupe non atteinte",
}

# États de séquence
NON_INITIALISE = "NON_INITIALISE"
PRET_COUPE = "PRET_COUPE"
OCCUPE_BRIDAGE = "OCCUPE_BRIDAGE"
OCCUPE_COUPE = "OCCUPE_COUPE"
OCCUPE_MOUVEMENT = "OCCUPE_MOUVEMENT"
PRET_LIGATURAGE = "PRET_LIGATURAGE"

# Actions demandées par les boutons
BRIDAGE = "bridage"
COUPE = "coupe"
POSITION = "position"


class Poste:

    def __init__(self, nom: str, axe: Axe, capteur_coupe: Filtre, capteur_ligaturage: Filtre,
                 compteurs, buzzer) -> None:
        self.nom = nom
        self.axe = axe
        self._capteurs = {cfg.POSITION_COUPE: capteur_coupe,
                          cfg.POSITION_LIGATURAGE: capteur_ligaturage}
        self._compteurs = compteurs
        self._buzzer = buzzer

        self.etat = NON_INITIALISE
        self.bride = False          # état RETENU, ne change qu'en fin de manœuvre
        self.ev_bridage = False     # sortie commandée
        self.ev_coupe = False       # sortie commandée
        self.libre_a = 0.0          # instant à partir duquel un appui est accepté (I3)
        self.arrive_a = 0.0         # instant d'arrivée dans la position courante (I7)

        self._echeance = 0.0        # fin de la phase en cours (bridage, coupe)
        self._phase_coupe = None    # "avant" | "impulsion" | "apres"
        self._cible = None          # position visée pendant un mouvement
        self._capteur_depart = None # surveillé pour D4, None en recherche lente
        self._budget_recale = False # budget déjà recalé sur le relâchement du galet de départ
        self._arret_a = None        # instant de détection de la fin de course cible
        self._referencement = False
        self._perte_depuis = None   # D5 : début de disparition de la fin de course

    # ── Lecture de l'état ─────────────────────────────────────────────────

    @property
    def position(self) -> str | None:
        """Position mécanique connue, ou None (mouvement, non initialisé)."""
        if self.etat in (PRET_COUPE, OCCUPE_BRIDAGE, OCCUPE_COUPE):
            return cfg.POSITION_COUPE
        if self.etat == PRET_LIGATURAGE:
            return cfg.POSITION_LIGATURAGE
        return None

    @property
    def en_mouvement(self) -> bool:
        return self.etat == OCCUPE_MOUVEMENT or self.axe.en_marche

    # ── Interlocks locaux (I2 à I6) ───────────────────────────────────────

    def refus_local(self, action: str, maintenant: float) -> str | None:
        """Motif de refus, ou None si le poste accepte l'action."""
        if self.etat not in (PRET_COUPE, PRET_LIGATURAGE):
            return f"I2 — poste occupé ({self.etat})"
        if maintenant < self.libre_a:
            return "I3 — temps de garde après action non écoulé"
        if action == COUPE and self.etat != PRET_COUPE:
            return "I4 — coupe interdite hors position coupe"
        if action == BRIDAGE and self.etat != PRET_COUPE:
            return "I5 — bridage figé hors position coupe"
        if action == POSITION and self.etat == PRET_COUPE and not self.bride:
            return "I6 — brider avant de partir en ligaturage"
        return None

    # ── Lancement des actions (appelé par le coordinateur, interlocks vérifiés) ──

    def lancer_bridage(self, maintenant: float) -> None:
        self.ev_bridage = not self.ev_bridage
        self.etat = OCCUPE_BRIDAGE
        self._echeance = maintenant + cfg.TEMPS_MANOEUVRE_BRIDAGE_S

    def lancer_coupe(self, maintenant: float) -> None:
        self.etat = OCCUPE_COUPE
        self._phase_coupe = "avant"
        self._echeance = maintenant + cfg.TEMPS_AVANT_COUPE_S

    def lancer_mouvement(self, maintenant: float) -> None:
        cible = cfg.POSITION_LIGATURAGE if self.etat == PRET_COUPE else cfg.POSITION_COUPE
        self._demarrer(cible, lent=False, referencement=False)

    def lancer_referencement(self, maintenant: float) -> None:
        """Ramène l'axe en POSITION_COUPE (LOGIQUE.md § 4.1)."""
        coupe = self._capteurs[cfg.POSITION_COUPE]
        ligaturage = self._capteurs[cfg.POSITION_LIGATURAGE]
        if coupe.stable and ligaturage.stable:
            raise Defaut("D2", f"{self.nom} : fins de course coupe ET ligaturage actives")
        if coupe.stable:
            self.etat = PRET_COUPE
            self.arrive_a = maintenant
            log.info("%s : déjà en position coupe", self.nom)
            return
        # Depuis la fin de course ligaturage : profil normal. Depuis une position
        # inconnue (arrêt en pleine course) : recherche lente, bornée par le budget.
        lent = not ligaturage.stable
        log.info("%s : référencement vers la position coupe (%s)", self.nom,
                 "recherche lente" if lent else "depuis la position ligaturage")
        self._demarrer(cfg.POSITION_COUPE, lent=lent, referencement=True)

    def neutraliser(self) -> None:
        """Défaut ou arrêt : ordre d'arrêt à l'axe, sorties commandées à 0, état oublié.

        L'attente de fin du thread et l'écriture de ENA sont faites par le
        coordinateur, qui traite les deux postes ensemble.
        """
        self.axe.demander_arret()
        self.ev_bridage = False
        self.ev_coupe = False
        self.bride = False          # relais à 0 → débridé
        self.etat = NON_INITIALISE
        self._phase_coupe = None
        self._cible = None
        self._arret_a = None
        self._perte_depuis = None

    # ── Progression, appelée à chaque tour de boucle ──────────────────────

    def avancer(self, maintenant: float) -> None:
        """Fait progresser l'action en cours et surveille les capteurs. Lève Defaut."""
        if self.etat == OCCUPE_BRIDAGE:
            if maintenant >= self._echeance:
                self.bride = self.ev_bridage
                self._terminer(maintenant, PRET_COUPE, f"ev_bridage_{self.nom}",
                               "bridé" if self.bride else "débridé")
        elif self.etat == OCCUPE_COUPE:
            self._avancer_coupe(maintenant)
        elif self.etat == OCCUPE_MOUVEMENT:
            self._avancer_mouvement(maintenant)
        self._surveiller_capteurs(maintenant)

    def _avancer_coupe(self, maintenant: float) -> None:
        if maintenant < self._echeance:
            return
        if self._phase_coupe == "avant":
            self.ev_coupe = True
            self._phase_coupe = "impulsion"
            self._echeance = maintenant + cfg.TEMPS_COUPE_S
        elif self._phase_coupe == "impulsion":
            self.ev_coupe = False
            self._phase_coupe = "apres"
            self._echeance = maintenant + cfg.TEMPS_APRES_COUPE_S
        else:
            self._phase_coupe = None
            self._terminer(maintenant, PRET_COUPE, f"ev_coupe_{self.nom}", "coupe terminée")

    def _avancer_mouvement(self, maintenant: float) -> None:
        cible = self._capteurs[self._cible]
        if self.axe.erreur is not None:
            raise Defaut("D1", f"{self.nom} : génération d'impulsions interrompue ({self.axe.erreur})")

        if self._arret_a is None:
            # Le galet de départ vient de se relâcher : l'axe est sur son point de
            # déclenchement, à une course nominale de la cible. Le budget repart
            # de là, pour que la marge au-delà de la cible vaille toujours
            # MOTEUR_MARGE_DEG — même si l'axe a démarré loin derrière son galet
            # (après un défaut D1). Avant ce relâchement, D4 borne le mouvement.
            if self._capteur_depart is not None and not self._budget_recale \
                    and not self._capteur_depart.brut:
                self.axe.etendre_budget(self.axe.pas + cfg.MOTEUR_BUDGET_PAS)
                self._budget_recale = True

            # En marche : on attend la fin de course cible.
            if cible.consecutifs >= cfg.CAPTEUR_LECTURES_ARRET:
                self.axe.demander_arret_apres(cfg.MOTEUR_SURCOURSE_PAS)
                self._arret_a = maintenant
            elif not self.axe.en_marche:
                # Le thread s'est arrêté seul : budget épuisé.
                raise Defaut("D8" if self._referencement else "D1",
                             f"{self.nom} : fin de course {self._cible} non atteinte "
                             f"en {self.axe.pas} pas")
            elif (self._capteur_depart is not None
                  and self.axe.pas >= cfg.MOTEUR_DEGAGEMENT_MAX_PAS
                  and self._capteur_depart.stable):
                raise Defaut("D4", f"{self.nom} : fin de course de départ toujours active "
                                   f"après {self.axe.pas} pas")
            return

        # Arrêt demandé : surcourse en cours, puis confirmation par stabilité.
        if not self.axe.en_marche and cible.stable:
            self._arrivee(maintenant)
        elif maintenant - self._arret_a > cfg.CONFIRMATION_CAPTEUR_MAX_S:
            raise Defaut("D5", f"{self.nom} : fin de course {self._cible} vue puis non confirmée")

    def _arrivee(self, maintenant: float) -> None:
        if not cfg.MOTEUR_MAINTIEN_EN_POSITION:
            self.axe.liberer()
        self.arrive_a = maintenant
        etat = PRET_LIGATURAGE if self._cible == cfg.POSITION_LIGATURAGE else PRET_COUPE
        message = f"arrivé en position {self._cible} ({self.axe.pas} pas)"
        referencement = self._referencement
        self._cible = None
        self._arret_a = None
        self._referencement = False
        # Pas de double bip au référencement : c'est « machine prête » qui le donne.
        self._terminer(maintenant, etat, f"moteur_{self.nom}", message, bip=not referencement)

    def _terminer(self, maintenant: float, etat: str, compteur: str, message: str,
                  bip: bool = True) -> None:
        """Fin commune de toute action : état, garde, compteur, double bip, journal."""
        self.etat = etat
        self.libre_a = maintenant + cfg.TEMPS_GARDE_APRES_ACTION_S
        self._compteurs.actionneur(compteur)
        if bip:
            self._buzzer.double_bip()
        log.info("%s : %s", self.nom, message)

    def _demarrer(self, cible: str, lent: bool, referencement: bool) -> None:
        depart = (cfg.POSITION_COUPE if cible == cfg.POSITION_LIGATURAGE
                  else cfg.POSITION_LIGATURAGE)
        capteur_cible = self._capteurs[cible]
        if capteur_cible.brut or capteur_cible.stable:
            raise Defaut("D3", f"{self.nom} : fin de course {cible} déjà active avant le départ")
        capteur_depart = self._capteurs[depart]
        self._capteur_depart = capteur_depart if capteur_depart.stable else None
        self._budget_recale = False

        direction = cfg.DIR_VERS_LIGATURAGE if cible == cfg.POSITION_LIGATURAGE else cfg.DIR_VERS_COUPE
        self.axe.preparer(direction)
        self.axe.lancer(cfg.MOTEUR_BUDGET_PAS, lent)
        self.etat = OCCUPE_MOUVEMENT
        self._cible = cible
        self._arret_a = None
        self._referencement = referencement

    # ── Surveillance permanente des capteurs (D2, D5) ─────────────────────

    def _surveiller_capteurs(self, maintenant: float) -> None:
        coupe = self._capteurs[cfg.POSITION_COUPE]
        ligaturage = self._capteurs[cfg.POSITION_LIGATURAGE]
        if coupe.stable and ligaturage.stable:
            raise Defaut("D2", f"{self.nom} : fins de course coupe ET ligaturage actives")

        attendue = self.position
        if attendue is None or self._capteurs[attendue].stable:
            self._perte_depuis = None
        elif self._perte_depuis is None:
            self._perte_depuis = maintenant
        elif maintenant - self._perte_depuis >= cfg.TOLERANCE_PERTE_CAPTEUR_S:
            raise Defaut("D5", f"{self.nom} : fin de course {attendue} perdue à l'arrêt")
