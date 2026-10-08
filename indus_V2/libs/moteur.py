# -*- coding: utf-8 -*-
"""
moteur.py — Un axe pas-à-pas : ENA / DIR via le MCP 0x25, impulsions PUL dans un thread.

Origine : Clean-and-Protech V4 libs/moteur.py (séquence ENA → DIR → pause →
impulsions, rampe linéaire) et libs/io_board.py (images des ports ENA / DIR).
Changements :
  - la boucle d'impulsions tourne dans un THREAD et teste un drapeau d'arrêt à
    chaque pas : la boucle principale continue de lire les capteurs pendant le
    mouvement (LOGIQUE.md § 2.4) ;
  - profil à 4 phases : accélération, palier, décélération, approche lente
    sans longueur fixe (LOGIQUE.md § 8) ;
  - budget de pas dur : le thread s'arrête de lui-même au dernier pas autorisé ;
  - retrait de la résolution par nom métier, des 8 drivers et du homing V4.

Partage entre threads : le thread d'impulsions ne touche QUE sa broche PUL. Il
ne fait jamais d'I2C. DIR et ENA sont écrits par la boucle principale, avant le
départ et après l'arrêt. Seuls le drapeau d'arrêt, la consigne de surcourse et
le compteur de pas sont partagés, chacun écrit par un seul côté : aucun verrou
n'est nécessaire.
"""

from __future__ import annotations

import logging
import math
import threading
import time

import lgpio

import config as cfg
from libs.materiel import ENA_TOUS_LIBRES, PORT_A, PORT_B, Mcp23017

log = logging.getLogger("vitis")


def _vitesse_profil(poste: str, pas: int) -> float:
    """Consigne de vitesse (pas/s) du profil normal de l'axe `poste`, au pas numéro `pas`."""
    v_app = cfg.MOTEUR_VITESSE_APPROCHE_SPS
    v_max = cfg.MOTEUR_VITESSE_POINTE_SPS[poste]      # < VITESSE_MAX si la course est courte
    fin_decel = cfg.MOTEUR_FIN_DECEL_PAS[poste]
    accel_pas, decel_pas = cfg.MOTEUR_ACCEL_PAS[poste], cfg.MOTEUR_DECEL_PAS[poste]
    if pas >= fin_decel:
        return v_app
    if pas < accel_pas:
        avancement, acceleration, longueur = pas, cfg.MOTEUR_ACCEL_SPS2[poste], accel_pas
    elif pas >= fin_decel - decel_pas:
        avancement, acceleration, longueur = fin_decel - pas, cfg.MOTEUR_DECEL_SPS2[poste], decel_pas
    else:
        return v_max
    if cfg.MOTEUR_RAMPES_EN_S:
        # Demi-cosinus : pente nulle aux deux bouts de la rampe, donc pas de
        # cassure de vitesse — c'est la cassure qui excite la mécanique.
        v = v_app + (v_max - v_app) * (1 - math.cos(math.pi * avancement / longueur)) / 2
    else:
        v = math.sqrt(v_app ** 2 + 2 * acceleration * avancement)
    return min(v, v_max)


# Périodes du profil normal de chaque axe (les courses diffèrent), calculées
# une fois : le thread ne fait qu'une lecture de tableau par pas. Au-delà du
# tableau : vitesse d'approche.
PERIODES_PROFIL = {poste: tuple(1.0 / _vitesse_profil(poste, i)
                                for i in range(cfg.MOTEUR_FIN_DECEL_PAS[poste]))
                   for poste in cfg.POSTES}
PERIODE_APPROCHE = 1.0 / cfg.MOTEUR_VITESSE_APPROCHE_SPS


def _avec_bit(octet: int, bit: int, niveau: int) -> int:
    return (octet | (1 << bit)) if niveau else (octet & ~(1 << bit) & 0xFF)


class PortsDrivers:
    """Les deux ports du MCP 0x25. Chaque écriture envoie l'octet complet."""

    def __init__(self, mcp: Mcp23017) -> None:
        self._mcp = mcp

    def ecrire_ena(self, bit: int, excite: bool) -> None:
        niveau = cfg.ENA_MOTEUR_EXCITE if excite else cfg.ENA_MOTEUR_LIBRE
        self._mcp.ecrire_port(PORT_B, _avec_bit(self._mcp.image(PORT_B), bit, niveau))

    def ecrire_dir(self, bit: int, niveau: int) -> None:
        self._mcp.ecrire_port(PORT_A, _avec_bit(self._mcp.image(PORT_A), bit, niveau))

    def liberer_tous(self) -> None:
        self._mcp.ecrire_port(PORT_B, ENA_TOUS_LIBRES)

    def tous_libres(self) -> bool:
        return self._mcp.image(PORT_B) == ENA_TOUS_LIBRES


class Axe:
    """Un axe : préparation (ENA, DIR) par la boucle, impulsions par un thread."""

    def __init__(self, poste: str, puce: int, broche_pul: int, bit_dir: int, bit_ena: int,
                 ports: PortsDrivers) -> None:
        self.poste = poste
        self._puce = puce
        self._pul = broche_pul
        self._bit_dir = bit_dir
        self._bit_ena = bit_ena
        self._ports = ports
        self._thread: threading.Thread | None = None
        self._arret = threading.Event()
        self._budget = 0                       # écrit par la boucle, lu par le thread
        self._surcourse: int | None = None     # écrit par la boucle, lu par le thread
        self.pas = 0                           # écrit par le thread, lu par la boucle
        self.erreur: Exception | None = None   # écrit par le thread, lu par la boucle

    # ── Côté boucle principale ────────────────────────────────────────────

    def preparer(self, direction: int) -> None:
        """Excite le moteur et fixe le sens. Accès I2C : boucle principale seulement."""
        self._ports.ecrire_ena(self._bit_ena, excite=True)
        time.sleep(cfg.MOTEUR_ENA_AVANT_DIR_S)
        self._ports.ecrire_dir(self._bit_dir, direction)
        time.sleep(cfg.MOTEUR_DIR_AVANT_PAS_S)

    def lancer(self, budget: int, lent: bool, vitesse_lente_sps: float | None = None) -> None:
        """Démarre le thread d'impulsions. `lent` : tout le trajet à vitesse d'approche.

        `vitesse_lente_sps` remplace la vitesse d'approche pour ce mouvement
        (scripts de test : déplacement manuel très lent)."""
        if self.en_marche:
            raise RuntimeError(f"axe {self.poste} : thread d'impulsions déjà en marche")
        self._arret.clear()
        self._budget = budget
        self._surcourse = None
        self.pas = 0
        self.erreur = None
        periodes = () if lent else PERIODES_PROFIL[self.poste]
        periode_lente = 1.0 / vitesse_lente_sps if vitesse_lente_sps else PERIODE_APPROCHE
        self._thread = threading.Thread(target=self._impulsions, args=(periodes, periode_lente),
                                        name=f"impulsions_{self.poste}", daemon=True)
        self._thread.start()

    @property
    def en_marche(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def demander_arret(self) -> None:
        """Arrêt au pas suivant (défaut, arrêt programme)."""
        self._arret.set()

    def etendre_budget(self, budget: int) -> None:
        """Repousse la borne de pas. Ne peut que l'augmenter."""
        if budget > self._budget:
            self._budget = budget

    def demander_arret_apres(self, pas: int) -> None:
        """Arrêt après encore `pas` pas (surcourse sur la fin de course). Premier appel seul retenu."""
        if self._surcourse is None:
            self._surcourse = max(0, int(pas))

    def attendre_fin(self, delai_s: float) -> bool:
        if self._thread is not None:
            self._thread.join(delai_s)
        return not self.en_marche

    def liberer(self) -> None:
        """ENA à « libre ». Accès I2C : boucle principale seulement."""
        self._ports.ecrire_ena(self._bit_ena, excite=False)

    # ── Côté thread d'impulsions ──────────────────────────────────────────

    def _impulsions(self, periodes: tuple, periode_lente: float) -> None:
        largeur_s = cfg.MOTEUR_LARGEUR_IMPULSION_US * 1e-6
        reste = None
        t_prochain = time.perf_counter()
        try:
            while self.pas < self._budget and not self._arret.is_set():
                if reste is None and self._surcourse is not None:
                    reste = self._surcourse
                if reste is not None:
                    if reste <= 0:
                        break
                    reste -= 1

                attente = t_prochain - time.perf_counter()
                if attente > 0:
                    time.sleep(attente)

                lgpio.gpio_write(self._puce, self._pul, 1)
                # Attente active : quelques dizaines de µs, trop court pour sleep().
                fin_impulsion = time.perf_counter() + largeur_s
                while time.perf_counter() < fin_impulsion:
                    pass
                lgpio.gpio_write(self._puce, self._pul, 0)    # front descendant = le pas
                t_pas = time.perf_counter()
                self.pas += 1

                periode = periodes[self.pas] if self.pas < len(periodes) else periode_lente
                # Échéance comptée depuis le pas RÉELLEMENT émis : un retard (GIL,
                # ordonnanceur) ralentit le moteur, il ne provoque jamais de rafale.
                t_prochain = t_pas + periode
        except Exception as erreur:                     # noqa: BLE001 — remonté à la boucle
            self.erreur = erreur
            try:
                lgpio.gpio_write(self._puce, self._pul, 0)
            except Exception:                           # noqa: BLE001
                pass
