# -*- coding: utf-8 -*-
"""
moteur.py — Un moteur de rotation : ENA / DIR via le MCP 0x25, impulsions PUL dans un thread.

Origine : indus V2 libs/moteur.py (thread d'impulsions, drapeau d'arrêt,
budget de pas dur, rampes en S), lui-même repris de Clean-and-Protech V4
libs/moteur.py et libs/io_board.py.
Changements V3 (LOGIQUE.md § 2.1 et § 8) :
  - trois profils au lieu d'un : OUVERT (rampe puis croisière jusqu'à l'ordre
    d'arrêt : rotation au maintien, passe rapide), LENT (vitesse constante, sans
    rampe : passe lente de confirmation), FERMÉ (rampe, croisière, rampe, arrêt
    sur un nombre de pas : centrage, recul) ;
  - rampes définies par une DURÉE (DUREE_RAMPE_ROTATION_S), pas par une
    accélération ;
  - la pause DIR → premier pas est faite PAR LE THREAD : la boucle principale
    n'attend plus jamais (les deux moteurs tournent en même temps) ;
  - plus d'approche lente, plus de surcourse, plus d'extension de budget.

Partage entre threads : le thread d'impulsions ne touche QUE sa broche PUL. Il
ne fait jamais d'I2C. DIR et ENA sont écrits par la boucle principale. Seuls le
drapeau d'arrêt et le compteur de pas sont partagés, chacun écrit par un seul
côté : aucun verrou n'est nécessaire.
"""

from __future__ import annotations

import functools
import logging
import math
import threading
import time

import lgpio

import config as cfg
from libs.materiel import ENA_TOUS_LIBRES, PORT_A, PORT_B, Mcp23017

log = logging.getLogger("vitis")


# ═══════════════════════════════════════════════════════════════════════════
#  PROFILS DE VITESSE  (calculés une fois, le thread ne lit qu'un tableau)
# ═══════════════════════════════════════════════════════════════════════════

def _vitesse_rampe(t: float, v_depart: float, v_cible: float) -> float:
    """Vitesse (pas/s) à l'instant `t` d'une rampe de DUREE_RAMPE_ROTATION_S."""
    avancement = min(t / cfg.DUREE_RAMPE_ROTATION_S, 1.0)
    if cfg.MOTEUR_RAMPES_EN_S:
        # Demi-cosinus : pente nulle aux deux bouts, donc pas de cassure de
        # vitesse — c'est la cassure qui excite la mécanique.
        avancement = (1 - math.cos(math.pi * avancement)) / 2
    return v_depart + (v_cible - v_depart) * avancement


@functools.lru_cache(maxsize=None)
def _rampe(v_depart_sps: float, v_cible_sps: float) -> tuple:
    """Périodes (s) des pas d'une rampe `v_depart_sps` → `v_cible_sps`.

    La rampe est découpée dans le TEMPS : chaque pas prend la vitesse de
    l'instant où il part. Sa longueur en pas dépend donc des vitesses.
    """
    periodes = []
    t = 0.0
    while t < cfg.DUREE_RAMPE_ROTATION_S:
        periode = 1.0 / _vitesse_rampe(t, v_depart_sps, v_cible_sps)
        periodes.append(periode)
        t += periode
    return tuple(periodes)


def periodes_rampe(v_cible_sps: float) -> tuple:
    """Rampe de démarrage : VITESSE_DEMARRAGE → `v_cible_sps`."""
    return _rampe(cfg.VITESSE_DEMARRAGE_SPS, v_cible_sps)


def vider_cache() -> None:
    """À appeler après un changement de vitesse ou de rampe (test_6 : réglage)."""
    _rampe.cache_clear()


def periodes_vers_butee(distance_pas: int, v_cible_sps: float) -> tuple:
    """Profil d'une rotation vers une butée située à ≈ `distance_pas`.

    Rampe de démarrage, croisière, puis rampe de RALENTISSEMENT qui atteint
    VITESSE_APPROCHE_BUTEE à ZONE_APPROCHE_BUTEE avant la butée ; ensuite, vitesse
    d'approche jusqu'au galet (ou jusqu'au budget de pas). Renvoie
    (périodes, période de la suite) pour Axe.lancer_vers().

    Trajet trop court pour monter à `v_cible_sps` et redescendre : la vitesse de
    croisière baisse de 15 % en 15 % jusqu'à ce que les deux rampes tiennent ;
    sinon, tout le trajet se fait à la vitesse d'approche.
    """
    v_approche = cfg.VITESSE_APPROCHE_BUTEE_SPS
    lente = 1.0 / v_approche
    fin_ralenti = distance_pas - cfg.ZONE_APPROCHE_BUTEE_PAS
    v = v_cible_sps
    while v > v_approche:
        montee = periodes_rampe(v)
        descente = tuple(reversed(_rampe(v_approche, v)))
        palier = fin_ralenti - len(montee) - len(descente)
        if palier >= 0:
            return montee + (1.0 / v,) * palier + descente, lente
        v *= 0.85
    return periodes_rampe(v_approche), lente


def periodes_vers_position(nombre_pas: int, v_cible_sps: float) -> tuple:
    """Profil FERMÉ de `nombre_pas` pas : rampe, croisière, rampe miroir.

    Trajet trop court pour les deux rampes complètes : chacune est tronquée à
    la moitié du trajet, la vitesse de pointe baisse d'autant (comme en V2).
    """
    montee = periodes_rampe(v_cible_sps)
    longueur = min(len(montee), nombre_pas // 2)
    croisiere = 1.0 / v_cible_sps
    milieu = nombre_pas - 2 * longueur
    return montee[:longueur] + (croisiere,) * milieu + tuple(reversed(montee[:longueur]))


# ═══════════════════════════════════════════════════════════════════════════
#  PORTS DIR / ENA
# ═══════════════════════════════════════════════════════════════════════════

def _avec_bit(octet: int, bit: int, niveau: int) -> int:
    return (octet | (1 << bit)) if niveau else (octet & ~(1 << bit) & 0xFF)


class PortsDrivers:
    """Les deux ports du MCP 0x25. Chaque écriture envoie l'octet complet,
    et seulement s'il change : une écriture de DIR inutile coûterait une
    transaction I2C par mouvement."""

    def __init__(self, mcp: Mcp23017) -> None:
        self._mcp = mcp

    def _ecrire(self, port: int, valeur: int) -> None:
        if valeur != self._mcp.image(port):
            self._mcp.ecrire_port(port, valeur)

    def ecrire_ena(self, bit: int, excite: bool) -> None:
        niveau = cfg.ENA_MOTEUR_EXCITE if excite else cfg.ENA_MOTEUR_LIBRE
        self._ecrire(PORT_B, _avec_bit(self._mcp.image(PORT_B), bit, niveau))

    def ecrire_dir(self, bit: int, niveau: int) -> None:
        self._ecrire(PORT_A, _avec_bit(self._mcp.image(PORT_A), bit, niveau))

    def est_libre(self, bit: int) -> bool:
        return bool(self._mcp.image(PORT_B) & (1 << bit)) == bool(cfg.ENA_MOTEUR_LIBRE)

    def liberer_tous(self) -> None:
        self._mcp.ecrire_port(PORT_B, ENA_TOUS_LIBRES)

    def tous_libres(self) -> bool:
        return self._mcp.image(PORT_B) == ENA_TOUS_LIBRES


# ═══════════════════════════════════════════════════════════════════════════
#  MOTEUR
# ═══════════════════════════════════════════════════════════════════════════

class Axe:
    """Un moteur : ENA et DIR par la boucle principale, impulsions par un thread."""

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
        self.pas = 0                           # écrit par le thread, lu par la boucle
        self.erreur: Exception | None = None   # écrit par le thread, lu par la boucle
        self.retard_max_s = 0.0                # écrit par le thread : pire retard d'une impulsion

    # ── Côté boucle principale ────────────────────────────────────────────

    def exciter(self) -> None:
        """ENA à « excité » (couple de maintien). Accès I2C : boucle principale seulement."""
        self._ports.ecrire_ena(self._bit_ena, excite=True)

    def liberer(self) -> None:
        """ENA à « libre ». Accès I2C : boucle principale seulement."""
        self._ports.ecrire_ena(self._bit_ena, excite=False)

    @property
    def libre(self) -> bool:
        return self._ports.est_libre(self._bit_ena)

    def lancer_vers(self, sens: str, budget: int, periodes: tuple, periode_suite: float) -> None:
        """Écrit DIR puis démarre le thread d'impulsions.

        `periodes` : périodes des premiers pas (rampe ou profil fermé) ;
        `periode_suite` : période des pas suivants, jusqu'au budget ou à l'arrêt.
        Le moteur doit déjà être excité.
        """
        if self.en_marche:
            raise RuntimeError(f"moteur {self.poste} : thread d'impulsions déjà en marche")
        niveau = (cfg.DIR_VERS_HORAIRE if sens == cfg.SENS_HORAIRE
                  else cfg.DIR_VERS_ANTIHORAIRE)[self.poste]
        self._ports.ecrire_dir(self._bit_dir, niveau)
        self._lancer(budget, periodes, periode_suite)

    def lancer_niveau(self, niveau_dir: int, budget: int, periodes: tuple, periode_suite: float) -> None:
        """Comme lancer_vers(), avec le niveau de DIR brut (test_5 : sens encore inconnu)."""
        if self.en_marche:
            raise RuntimeError(f"moteur {self.poste} : thread d'impulsions déjà en marche")
        self._ports.ecrire_dir(self._bit_dir, niveau_dir)
        self._lancer(budget, periodes, periode_suite)

    def _lancer(self, budget: int, periodes: tuple, periode_suite: float) -> None:
        self._arret.clear()
        self.pas = 0
        self.erreur = None
        self.retard_max_s = 0.0
        self._thread = threading.Thread(target=self._impulsions,
                                        args=(budget, periodes, periode_suite),
                                        name=f"impulsions_{self.poste}", daemon=True)
        self._thread.start()

    @property
    def en_marche(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def demander_arret(self) -> None:
        """Arrêt au pas suivant (relâchement, butée, défaut, arrêt programme)."""
        self._arret.set()

    def attendre_fin(self, delai_s: float) -> bool:
        if self._thread is not None:
            self._thread.join(delai_s)
        return not self.en_marche

    # ── Côté thread d'impulsions ──────────────────────────────────────────

    def _impulsions(self, budget: int, periodes: tuple, periode_suite: float) -> None:
        largeur_s = cfg.MOTEUR_LARGEUR_IMPULSION_US * 1e-6
        # Fiche du driver : DIR stable avant le premier front. Attendu ICI,
        # pas dans la boucle principale, qui ne doit jamais s'arrêter.
        t_prochain = time.perf_counter() + cfg.MOTEUR_DIR_AVANT_PAS_S
        try:
            while self.pas < budget and not self._arret.is_set():
                attente = t_prochain - time.perf_counter()
                if attente > 0:
                    time.sleep(attente)
                    if self._arret.is_set():
                        break
                # Diagnostic : de combien cette impulsion part-elle après son
                # échéance ? Un long retard (Python, système) fige le rotor puis
                # le relance à pleine vitesse : cause possible de décrochage.
                retard = time.perf_counter() - t_prochain
                if retard > self.retard_max_s:
                    self.retard_max_s = retard

                lgpio.gpio_write(self._puce, self._pul, 1)
                # Attente active : quelques dizaines de µs, trop court pour sleep().
                fin_impulsion = time.perf_counter() + largeur_s
                while time.perf_counter() < fin_impulsion:
                    pass
                lgpio.gpio_write(self._puce, self._pul, 0)    # front descendant = le pas
                t_pas = time.perf_counter()
                self.pas += 1

                periode = periodes[self.pas] if self.pas < len(periodes) else periode_suite
                # Échéance comptée depuis le pas RÉELLEMENT émis : un retard (GIL,
                # ordonnanceur) ralentit le moteur, il ne provoque jamais de rafale.
                t_prochain = t_pas + periode
        except Exception as erreur:                     # noqa: BLE001 — remonté à la boucle
            self.erreur = erreur
            try:
                lgpio.gpio_write(self._puce, self._pul, 0)
            except Exception:                           # noqa: BLE001
                pass
