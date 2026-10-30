# -*- coding: utf-8 -*-
"""
poste.py — Machine à états d'un poste (mère ou fille). LOGIQUE.md § 3 à § 6.

Un poste possède son mandrin, sa coupe et son moteur de rotation. Il applique
ses interlocks (I1 à I5) et détecte ses défauts (D1, D2, D4, D5, D8, D9). Il ne
connaît PAS l'autre poste : en V3 les deux postes sont totalement
indépendants. machine.py ne fait que lui transmettre les appuis.

Règle centrale (LOGIQUE.md § 2) : une commande d'actionneur n'est jamais
instantanée. Chaque action a une durée ; l'état de l'actionneur (mandrin
fermé, position) ne change qu'à la FIN de l'action ; pendant l'action le poste
est occupé et ses boutons sont refusés.

Position : comptée en pas depuis la butée ANTIHORAIRE (0 = butée antihoraire,
`plage` = butée horaire), mesurée à l'initialisation, recalée à chaque arrivée
sur une butée.

Le poste n'écrit AUCUNE sortie relais : il expose ev_mandrin et ev_coupe, et
machine.py compose l'octet du port. Seul le moteur (ENA / DIR) est piloté d'ici.

Origine : indus V2 libs/poste.py (machine à états, séquence de coupe, garde
après action, surveillance D2 / D5), réécrit pour la rotation du mandrin.
"""

from __future__ import annotations

import logging

import config as cfg
from libs.entrees import BRIDAGE, COUPE, ROTATION_MOINS, ROTATION_PLUS, Entrees
from libs.moteur import Axe, periodes_rampe, periodes_vers_butee, periodes_vers_position

log = logging.getLogger("vitis")


class Defaut(Exception):
    """Défaut d'un poste. Levé n'importe où dans le poste, traité par machine.py."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code} — {detail}")
        self.code = code
        self.detail = detail


DESCRIPTION_DEFAUTS = {
    "D1": "butée non vue : la rotation a dépassé la plage + la marge (protection du tuyau)",
    "D2": "les deux butées du même poste actives",
    "D4": "butée de départ toujours active : le moteur ne tourne pas",
    "D5": "butée inattendue, perdue à l'arrêt, ou non confirmée à l'arrivée",
    "D6": "erreur de bus I2C",
    "D7": "configuration d'un MCP23017 perdue",
    "D8": "initialisation : butée non trouvée",
    "D9": "initialisation : plage mesurée hors tolérance",
}

# États (LOGIQUE.md § 3)
ATTENTE_ACQUITTEMENT = "ATTENTE_ACQUITTEMENT"
INITIALISATION = "INITIALISATION"
PRET = "PRET"
MANOEUVRE_MANDRIN = "MANOEUVRE_MANDRIN"
COUPE_EN_COURS = "COUPE"
ROTATION = "ROTATION"
RECENTRAGE = "RECENTRAGE"
DEFAUT = "DEFAUT"

# Moteur arrêté, position connue : la surveillance D5 « à l'arrêt » s'applique.
_ETATS_AU_REPOS = (PRET, MANOEUVRE_MANDRIN, COUPE_EN_COURS)

# Modes de fin d'un mouvement
_SUR_BUTEE = "butée"          # s'arrête sur la butée du sens de rotation
_SUR_COMPTE = "compte"        # s'arrête sur un nombre de pas (profil fermé)
_AU_RELACHEMENT = "maintien"  # s'arrête au relâchement du bouton, ou sur la butée
_DEGAGEMENT = "dégagement"    # quitte la butée de départ, puis RECUL_CONFIRMATION_PAS de plus


def _signe(sens: str) -> int:
    return 1 if sens == cfg.SENS_HORAIRE else -1


class Poste:

    def __init__(self, nom: str, axe: Axe, entrees: Entrees, compteurs, buzzer) -> None:
        self.nom = nom
        self.axe = axe
        self._entrees = entrees
        self._butees = {sens: entrees.butee(nom, sens) for sens in cfg.SENS}
        self._compteurs = compteurs
        self._buzzer = buzzer

        self.etat = ATTENTE_ACQUITTEMENT
        self.mandrin_ferme = False  # état RETENU, ne change qu'en fin de manœuvre
        self.ev_mandrin = False     # sortie commandée
        self.ev_coupe = False       # sortie commandée
        self.libre_a = 0.0          # instant à partir duquel un appui est accepté (I2)
        self.plage: int | None = None   # pas entre les deux butées, mesurée à l'initialisation

        self._pos = 0               # compteur de pas signé (+ = horaire), origine arbitraire
        self._zero: int | None = None   # valeur de _pos sur la butée antihoraire
        self._echeance = 0.0        # fin de la phase en cours
        self._phase: str | None = None
        self._mvt: dict | None = None
        self._cotes: tuple = ()     # initialisation : ordre des deux butées
        self._cote = 0
        # Initialisation : point de détection de chaque butée (compteur de pas),
        # en passe rapide et en passe lente. Lus par test_6 pour le diagnostic.
        self.detection_rapide: dict = {}
        self.repere_lent: dict = {}
        self._repos_ref = None      # D5 à l'arrêt : état des butées au début du repos
        self._repos_ecart_depuis = None
        self.dernier_ecart_recalage: int | None = None   # lu par le rodage (test_7)

    # ── Lecture de l'état ─────────────────────────────────────────────────

    @property
    def position(self) -> int | None:
        """Pas depuis la butée antihoraire, ou None (non initialisé)."""
        if self._zero is None:
            return None
        return self._position_courante() - self._zero

    @property
    def en_mouvement(self) -> bool:
        return self._mvt is not None or self.axe.en_marche

    def degres(self, pas: int | None) -> str:
        return "?" if pas is None else f"{pas / cfg.PAS_PAR_DEGRE:.1f}°"

    def _position_courante(self) -> int:
        if self._mvt is None:
            return self._pos
        return self._mvt["origine"] + _signe(self._mvt["sens"]) * self.axe.pas

    def sens_du_bouton(self, action: str) -> str:
        plus = cfg.SENS_ROTATION_PLUS[self.nom]
        return plus if action == ROTATION_PLUS else cfg.sens_oppose(plus)

    # ── Interlocks (LOGIQUE.md § 5) ───────────────────────────────────────

    def refus(self, action: str, maintenant: float) -> str | None:
        """Motif de refus d'un bouton du poste, ou None si l'action est acceptée."""
        if self.etat in (ATTENTE_ACQUITTEMENT, INITIALISATION, DEFAUT):
            return f"I1 — poste non initialisé ({self.etat})"
        if self.etat != PRET:
            return f"I2 — poste occupé ({self.etat})"
        if maintenant < self.libre_a:
            return "I2 — temps de garde après action non écoulé"
        if action == COUPE and not self.mandrin_ferme:
            return "I3 — coupe interdite mandrin ouvert"
        if action in (ROTATION_PLUS, ROTATION_MOINS):
            sens = self.sens_du_bouton(action)
            butee = self._butees[sens]
            if butee.stable or butee.brut or self._budget_rotation(sens) <= 0:
                return f"I4 — butée {sens} atteinte, seul le sens opposé est accepté"
            autre = ROTATION_MOINS if action == ROTATION_PLUS else ROTATION_PLUS
            if self._entrees.tenu(f"{autre}_{self.nom}"):
                return "I5 — les deux boutons de rotation sont enfoncés"
        return None

    def refus_acquittement(self, maintenant: float) -> str | None:
        """ACQUITTEMENT : initialisation hors marche, recentrage en PRET, refusé sinon."""
        if self.etat in (ATTENTE_ACQUITTEMENT, DEFAUT):
            return None
        if self.etat != PRET:
            return f"I2 — poste occupé ({self.etat})"
        if maintenant < self.libre_a:
            return "I2 — temps de garde après action non écoulé"
        return None

    # ── Lancement des actions (interlocks déjà vérifiés) ──────────────────

    def lancer(self, action: str, maintenant: float) -> None:
        if action == BRIDAGE:
            self.ev_mandrin = not self.ev_mandrin
            self.etat = MANOEUVRE_MANDRIN
            self._echeance = maintenant + cfg.TEMPS_MANOEUVRE_MANDRIN_S
        elif action == COUPE:
            self.etat = COUPE_EN_COURS
            self._phase = "avant"
            self._echeance = maintenant + cfg.TEMPS_AVANT_COUPE_S
        else:
            bouton = f"{action}_{self.nom}"
            self.lancer_rotation(self.sens_du_bouton(action), bouton)

    def lancer_rotation(self, sens: str, bouton: str | None = None) -> None:
        """Rotation à la vitesse de croisière. `bouton` : arrêt à son relâchement ;
        None : jusqu'à la butée (rodage). Ralentit d'elle-même à l'approche de la
        butée (ZONE_APPROCHE_BUTEE). Bornée par la protection du tuyau."""
        distance = self.plage - self.position if sens == cfg.SENS_HORAIRE else self.position
        periodes, suite = periodes_vers_butee(distance, cfg.VITESSE_CROISIERE_SPS)
        self._demarrer(sens, _AU_RELACHEMENT if bouton else _SUR_BUTEE,
                       self._budget_rotation(sens), periodes, suite,
                       bouton=bouton, code_budget="D1", code_inattendu="D5")
        self.etat = ROTATION

    def acquitter(self, maintenant: float) -> None:
        """ACQUITTEMENT accepté : initialisation complète, ou recentrage en marche."""
        if self.etat == PRET:
            self._lancer_recentrage(maintenant)
        else:
            self._lancer_initialisation(maintenant)

    def neutraliser(self, etat: str = DEFAUT) -> None:
        """Défaut ou arrêt : ordre d'arrêt au moteur, sorties commandées à 0, position oubliée.

        L'attente de fin du thread et l'écriture des relais sont faites par
        machine.py. Le moteur reste excité.
        """
        self.axe.demander_arret()
        self.ev_mandrin = False
        self.ev_coupe = False
        self.mandrin_ferme = False      # relais à 0 → mandrin ouvert
        self.etat = etat
        self._phase = None
        self._mvt = None
        self._zero = None
        self.plage = None
        self._repos_ref = None

    def _budget_rotation(self, sens: str) -> int:
        """Pas autorisés dans `sens` depuis la position : jusqu'à la butée + la marge."""
        if self.position is None or self.plage is None:
            return 0
        if sens == cfg.SENS_HORAIRE:
            return self.plage + cfg.MARGE_DEPASSEMENT_PAS - self.position
        return self.position + cfg.MARGE_DEPASSEMENT_PAS

    # ── Progression, appelée à chaque tour de boucle ──────────────────────

    def avancer(self, maintenant: float) -> None:
        """Fait progresser l'action en cours et surveille les butées. Lève Defaut."""
        if self.etat in (ATTENTE_ACQUITTEMENT, DEFAUT):
            return
        if self.etat == MANOEUVRE_MANDRIN:
            if maintenant >= self._echeance:
                self.mandrin_ferme = self.ev_mandrin
                self._terminer(maintenant, f"ev_mandrin_{self.nom}",
                               "mandrin fermé" if self.mandrin_ferme else "mandrin ouvert")
        elif self.etat == COUPE_EN_COURS:
            self._avancer_coupe(maintenant)
        elif self.etat == ROTATION:
            self._avancer_rotation(maintenant)
        elif self.etat == RECENTRAGE:
            self._avancer_recentrage(maintenant)
        elif self.etat == INITIALISATION:
            self._avancer_initialisation(maintenant)
        self._surveiller_butees(maintenant)

    def _terminer(self, maintenant: float, compteur: str | None, message: str,
                  garde: float = cfg.TEMPS_GARDE_APRES_ACTION_S, bip: bool = True) -> None:
        """Fin commune de toute action : état, garde, compteur, double bip, journal."""
        self.etat = PRET
        self._phase = None
        self.libre_a = maintenant + garde
        if compteur:
            self._compteurs.actionneur(compteur)
        if bip:
            self._buzzer.double_bip()
        log.info("%s : %s", self.nom, message)

    def _avancer_coupe(self, maintenant: float) -> None:
        """Séquence de coupe, inchangée depuis la V2 (LOGIQUE.md § 3.5)."""
        if maintenant < self._echeance:
            return
        if self._phase == "avant":
            self.ev_coupe = True
            self._phase = "impulsion"
            self._echeance = maintenant + cfg.TEMPS_COUPE_S
        elif self._phase == "impulsion":
            self.ev_coupe = False
            self._phase = "apres"
            self._echeance = maintenant + cfg.TEMPS_APRES_COUPE_S
        else:
            self._terminer(maintenant, f"ev_coupe_{self.nom}", "coupe terminée")

    # ── Rotation ──────────────────────────────────────────────────────────

    def _avancer_rotation(self, maintenant: float) -> None:
        fin = self._avancer_mouvement(maintenant)
        if fin is None:
            return
        sens = fin["sens"]
        if fin["raison"] == _SUR_BUTEE:
            self._recaler(fin)
            self._buzzer.bip_court()
            message = f"rotation {sens} jusqu'à la butée"
        else:
            message = f"rotation {sens}, arrêt à {self.degres(self.position)}"
        self._terminer(maintenant, f"rotations_{self.nom}", message,
                       garde=cfg.TEMPS_GARDE_APRES_ROTATION_S, bip=False)

    def _recaler(self, fin: dict) -> None:
        """Arrivée confirmée sur une butée : la position devient exacte.

        La référence est le point de DÉTECTION de la butée, comme à
        l'initialisation ; les quelques pas faits après la détection (retard
        d'arrêt) sont gardés en plus.
        """
        sens = fin["sens"]
        attendue = self.plage if sens == cfg.SENS_HORAIRE else 0
        ecart = (fin["detection"] - self._zero) - attendue
        if abs(ecart) > cfg.ECART_RECALAGE_MAX_PAS:
            # Pas de défaut (100 % manuel) : une piste pour le diagnostic de pas perdus.
            log.warning("%s : butée %s vue à %+d pas (%+.2f°) de la position comptée — recalage",
                        self.nom, sens, ecart, ecart / cfg.PAS_PAR_DEGRE)
        self._pos -= ecart
        self.dernier_ecart_recalage = ecart

    # ── Recentrage (ACQUITTEMENT en marche, LOGIQUE.md § 3.4) ─────────────

    def _lancer_recentrage(self, maintenant: float) -> None:
        self.etat = RECENTRAGE
        self._phase = "ouverture"
        self._echeance = maintenant
        if self.ev_mandrin or self.mandrin_ferme:
            # Le mandrin s'ouvre AVANT de tourner : une branche serrée serait vrillée.
            self.ev_mandrin = False
            self._echeance = maintenant + cfg.TEMPS_MANOEUVRE_MANDRIN_S
            self._compteurs.actionneur(f"ev_mandrin_{self.nom}")
            log.info("%s : recentrage — ouverture du mandrin d'abord", self.nom)

    def _avancer_recentrage(self, maintenant: float) -> None:
        if self._phase == "ouverture":
            if maintenant < self._echeance:
                return
            self.mandrin_ferme = False
            self._phase = "deplacement"
            if not self._deplacer_vers(self.plage // 2):
                self._terminer(maintenant, None, f"déjà au centre ({self.degres(self.position)})")
            return
        if self._avancer_mouvement(maintenant) is not None:
            self._terminer(maintenant, f"rotations_{self.nom}",
                           f"recentré à {self.degres(self.position)}")

    def _deplacer_vers(self, cible: int) -> bool:
        """Profil fermé jusqu'à la position `cible`. False si déjà à la tolérance près."""
        ecart = cible - self.position
        if abs(ecart) <= cfg.TOLERANCE_CENTRE_PAS:
            return False
        sens = cfg.SENS_HORAIRE if ecart > 0 else cfg.SENS_ANTIHORAIRE
        self._demarrer(sens, _SUR_COMPTE, abs(ecart),
                       periodes_vers_position(abs(ecart), cfg.VITESSE_RECENTRAGE_SPS),
                       1.0 / cfg.VITESSE_RECENTRAGE_SPS, code_budget="D1", code_inattendu="D5")
        return True

    # ── Initialisation : deux butées en deux passes, puis centrage (§ 3.1) ──

    def _lancer_initialisation(self, maintenant: float) -> None:
        mandrin_a_ouvrir = self.ev_mandrin or self.mandrin_ferme
        self.neutraliser(INITIALISATION)            # relais à 0 : le mandrin s'ouvre
        self._pos = 0
        self.detection_rapide = {}
        self.repere_lent = {}
        self._cotes = (cfg.INIT_PREMIER_SENS, cfg.sens_oppose(cfg.INIT_PREMIER_SENS))
        self._cote = 0
        self.axe.exciter()
        attente = cfg.MOTEUR_ENA_AVANT_DIR_S
        if mandrin_a_ouvrir:
            attente = max(attente, cfg.TEMPS_MANOEUVRE_MANDRIN_S)
        self._phase = "ouverture"
        self._echeance = maintenant + attente
        log.info("%s : initialisation — %srecherche des butées %s puis %s, puis centrage",
                 self.nom, "ouverture du mandrin, " if mandrin_a_ouvrir else "",
                 self._cotes[0], self._cotes[1])

    def _avancer_initialisation(self, maintenant: float) -> None:
        if self._phase == "ouverture":
            if maintenant >= self._echeance:
                self.mandrin_ferme = False
                self._passe_rapide()
            return
        fin = self._avancer_mouvement(maintenant)
        if fin is None:
            return
        sens = self._cotes[self._cote]
        if self._phase == "rapide":
            self.detection_rapide[sens] = fin["detection"]
            self._recul(sens)
        elif self._phase == "recul":
            if self._butees[sens].brut:
                raise Defaut("D4", f"{self.nom} : butée {sens} toujours active après un recul de "
                                   f"{cfg.RECUL_CONFIRMATION_DEG:.1f}°")
            self._phase = "lente"
            self._demarrer(sens, _SUR_BUTEE, cfg.BUDGET_CONFIRMATION_PAS, (),
                           1.0 / cfg.VITESSE_RECHERCHE_LENTE_SPS,
                           code_budget="D8", code_inattendu="D8", quoi="passe lente de confirmation")
        elif self._phase == "lente":
            self.repere_lent[sens] = fin["detection"]
            rapide = self.detection_rapide.get(sens)
            if rapide is not None:
                ecart = _signe(sens) * (rapide - fin["detection"])
                log.info("%s : butée %s confirmée en passe lente (écart avec la passe rapide %+.2f°)",
                         self.nom, sens, ecart / cfg.PAS_PAR_DEGRE)
            else:
                log.info("%s : butée %s confirmée en passe lente (départ sur la butée)", self.nom, sens)
            if self._cote == 0:
                self._cote = 1
                self._passe_rapide()
            else:
                self._fin_mesure(maintenant)
        elif self._phase == "centrage":
            self._fin_initialisation(maintenant)

    def _fin_initialisation(self, maintenant: float) -> None:
        self._terminer(maintenant, None,
                       f"initialisé — plage {self.degres(self.plage)} ({self.plage} pas), "
                       f"mandrin centré à {self.degres(self.position)}")

    def _passe_rapide(self) -> None:
        sens = self._cotes[self._cote]
        self._phase = "rapide"
        if self._butees[sens].stable:
            log.info("%s : déjà sur la butée %s", self.nom, sens)
            self.detection_rapide[sens] = None
            self._recul(sens)
            return
        if self._cote == 0:
            # Première butée : position inconnue, pas de ralentissement possible.
            periodes = periodes_rampe(cfg.VITESSE_RECHERCHE_RAPIDE_SPS)
            suite = 1.0 / cfg.VITESSE_RECHERCHE_RAPIDE_SPS
        else:
            # Seconde butée : à une plage de la première. On ralentit dès la plage
            # nominale moins sa tolérance, pour arriver lentement même si la plage
            # réelle est la plus courte acceptée.
            distance = cfg.PLAGE_NOMINALE_PAS[self.nom] - cfg.PLAGE_TOLERANCE_PAS
            periodes, suite = periodes_vers_butee(distance, cfg.VITESSE_RECHERCHE_RAPIDE_SPS)
        self._demarrer(sens, _SUR_BUTEE, cfg.BUDGET_RECHERCHE_RAPIDE_PAS[self.nom], periodes, suite,
                       code_budget="D8", code_inattendu="D8")

    def _recul(self, sens: str) -> None:
        """Quitte la butée `sens`, puis recule encore de RECUL_CONFIRMATION_PAS.

        Le recul est compté depuis le RELÂCHEMENT de la butée, pas depuis le
        départ : après un D1, le mandrin peut être jusqu'à la marge derrière sa
        butée, et un recul fixe ne suffirait pas à la relâcher (trouvé sur banc
        logiciel). Avant le relâchement, D4 borne le mouvement.
        """
        self._phase = "recul"
        self._demarrer(cfg.sens_oppose(sens), _DEGAGEMENT,
                       cfg.DEGAGEMENT_MAX_PAS + cfg.RECUL_CONFIRMATION_PAS,
                       periodes_rampe(cfg.VITESSE_RECENTRAGE_SPS), 1.0 / cfg.VITESSE_RECENTRAGE_SPS,
                       code_budget="D4", code_inattendu="D8")

    def _fin_mesure(self, maintenant: float) -> None:
        anti, hor = self.repere_lent[cfg.SENS_ANTIHORAIRE], self.repere_lent[cfg.SENS_HORAIRE]
        plage = hor - anti
        nominale = cfg.PLAGE_NOMINALE_PAS[self.nom]
        log.info("%s : plage mesurée %d pas = %.1f° (nominale %.1f°)",
                 self.nom, plage, plage / cfg.PAS_PAR_DEGRE, cfg.PLAGE_NOMINALE_DEG[self.nom])
        if abs(plage - nominale) > cfg.PLAGE_TOLERANCE_PAS:
            raise Defaut("D9", f"{self.nom} : plage mesurée {plage / cfg.PAS_PAR_DEGRE:.1f}° au lieu de "
                               f"{cfg.PLAGE_NOMINALE_DEG[self.nom]:.1f}° ± {cfg.PLAGE_TOLERANCE_DEG:.1f}°")
        self._zero = anti
        self.plage = plage
        self._phase = "centrage"
        if not self._deplacer_vers(plage // 2):
            self._fin_initialisation(maintenant)

    # ── Mouvement : démarrage, surveillance, fin ──────────────────────────

    def _demarrer(self, sens: str, mode: str, budget: int, periodes: tuple, periode_suite: float,
                  bouton: str | None = None, code_budget: str = "D1", code_inattendu: str = "D5",
                  quoi: str = "") -> None:
        oppose = cfg.sens_oppose(sens)
        self._mvt = {
            "sens": sens, "mode": mode, "bouton": bouton, "budget": budget,
            "origine": self._pos,
            # Butée qu'on quitte : surveillée pour D4 tant qu'elle ne s'est pas relâchée.
            "depart": oppose if (self._butees[oppose].stable or self._butees[oppose].brut) else None,
            "arret_a": None, "raison": None, "detection": None, "relache_a": None,
            "code_budget": code_budget, "code_inattendu": code_inattendu, "quoi": quoi,
        }
        self._repos_ref = None
        self.axe.lancer_vers(sens, budget, periodes, periode_suite)

    def _avancer_mouvement(self, maintenant: float) -> dict | None:
        """Surveille le mouvement en cours. Renvoie le mouvement terminé (dict), ou None."""
        m = self._mvt
        sens, oppose = m["sens"], cfg.sens_oppose(m["sens"])
        cible, autre = self._butees[sens], self._butees[oppose]
        if self.axe.erreur is not None:
            raise Defaut(m["code_budget"], f"{self.nom} : génération d'impulsions interrompue ({self.axe.erreur})")

        if m["depart"] is not None and not autre.stable and not autre.brut:
            m["depart"] = None                  # la butée de départ s'est relâchée (anti-rebond compris)
        if m["depart"] is None and m["relache_a"] is None:
            m["relache_a"] = self.axe.pas
        if m["depart"] is not None and self.axe.pas >= cfg.DEGAGEMENT_MAX_PAS and autre.stable:
            raise Defaut("D4", f"{self.nom} : butée {oppose} toujours active après {self.axe.pas} pas")
        if m["depart"] is None and autre.consecutifs >= cfg.CAPTEUR_LECTURES_ARRET:
            self.axe.demander_arret()
            raise Defaut(m["code_inattendu"], f"{self.nom} : butée {oppose} vue en tournant vers {sens} "
                                              "(sens de rotation ou attribution des butées à vérifier)")

        if m["arret_a"] is None:
            if m["mode"] in (_SUR_BUTEE, _AU_RELACHEMENT) and cible.consecutifs >= cfg.CAPTEUR_LECTURES_ARRET:
                self.axe.demander_arret()
                m["arret_a"], m["raison"] = maintenant, _SUR_BUTEE
                m["detection"] = self._position_courante()
            elif m["mode"] in (_SUR_COMPTE, _DEGAGEMENT) and cible.consecutifs >= cfg.CAPTEUR_LECTURES_ARRET:
                self.axe.demander_arret()
                raise Defaut(m["code_inattendu"], f"{self.nom} : butée {sens} vue pendant un "
                                                  "déplacement vers une position")
            elif m["mode"] == _AU_RELACHEMENT and not self._relachement_ok(m["bouton"]):
                self.axe.demander_arret()
                m["arret_a"], m["raison"] = maintenant, _AU_RELACHEMENT
            elif (m["mode"] == _DEGAGEMENT and m["relache_a"] is not None
                  and self.axe.pas >= m["relache_a"] + cfg.RECUL_CONFIRMATION_PAS):
                self.axe.demander_arret()
                m["arret_a"], m["raison"] = maintenant, _SUR_COMPTE
            elif not self.axe.en_marche:
                if m["mode"] == _SUR_COMPTE and self.axe.pas >= m["budget"]:
                    m["arret_a"], m["raison"] = maintenant, _SUR_COMPTE
                else:
                    # Le thread s'est arrêté seul : budget épuisé, la butée n'a pas été vue.
                    raise Defaut(m["code_budget"], f"{self.nom} : butée {sens} non vue après "
                                                   f"{self.axe.pas} pas ({self.degres(self.axe.pas)})"
                                                   + (f" — {m['quoi']}" if m["quoi"] else ""))
            if m["arret_a"] is None:
                return None

        if self.axe.en_marche:
            if maintenant - m["arret_a"] > cfg.ARRET_THREAD_MAX_S:
                raise Defaut(m["code_budget"], f"{self.nom} : le thread d'impulsions ne s'arrête pas")
            return None
        if m["raison"] == _SUR_BUTEE and not cible.stable:
            # Confirmation de l'arrivée par le signal stable.
            if maintenant - m["arret_a"] > cfg.CONFIRMATION_CAPTEUR_MAX_S:
                raise Defaut("D5", f"{self.nom} : butée {sens} vue puis non confirmée")
            return None
        self._pos = self._position_courante()
        self._mvt = None
        return m

    def _relachement_ok(self, bouton: str) -> bool:
        """True tant que la rotation au maintien doit continuer (lecture BRUTE)."""
        if not self._entrees.tenu(bouton):
            return False
        action, _, _ = bouton.rpartition(f"_{self.nom}")
        autre = ROTATION_MOINS if action == ROTATION_PLUS else ROTATION_PLUS
        return not self._entrees.tenu(f"{autre}_{self.nom}")

    # ── Surveillance permanente des butées (D2, D5) ───────────────────────

    def _surveiller_butees(self, maintenant: float) -> None:
        horaire, anti = self._butees[cfg.SENS_HORAIRE], self._butees[cfg.SENS_ANTIHORAIRE]
        if horaire.stable and anti.stable:
            self.axe.demander_arret()
            raise Defaut("D2", f"{self.nom} : butées horaire ET antihoraire actives")

        if self.etat not in _ETATS_AU_REPOS or self._mvt is not None:
            self._repos_ref = None
            self._repos_ecart_depuis = None
            return
        etat_butees = (horaire.stable, anti.stable)
        if self._repos_ref is None:
            self._repos_ref = etat_butees
        if etat_butees == self._repos_ref:
            self._repos_ecart_depuis = None
        elif self._repos_ecart_depuis is None:
            self._repos_ecart_depuis = maintenant
        elif maintenant - self._repos_ecart_depuis >= cfg.TOLERANCE_PERTE_CAPTEUR_S:
            raise Defaut("D5", f"{self.nom} : une butée a changé d'état moteur arrêté "
                               f"(horaire {self._repos_ref[0]} → {horaire.stable}, "
                               f"antihoraire {self._repos_ref[1]} → {anti.stable})")
