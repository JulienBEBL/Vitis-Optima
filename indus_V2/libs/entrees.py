# -*- coding: utf-8 -*-
"""
entrees.py — Boutons et fins de course : lecture, anti-rebond, fronts.

Origine : Vitis V1 indus/vitis_optima.py, classe `Boutons` (anti-rebond par
temps de stabilité, non bloquant, une seule lecture I2C par port et par tour).
Élargie à deux MCP, 7 boutons et 4 fins de course.

Deux usages du même filtre, volontairement opposés :
  - BOUTON : on agit sur le front du signal STABLE. Un bouton maintenu ne
    produit qu'un seul front, donc ne répète jamais l'action.
  - FIN DE COURSE : on ARRÊTE le moteur sur le signal BRUT (lectures
    consécutives), puis on CONFIRME l'arrivée sur le signal stable. Attendre la
    stabilité avant d'arrêter coûterait des degrés de dépassement.
"""

from __future__ import annotations

import config as cfg
from libs.materiel import PORT_B, Mcp23017

# Noms canoniques des boutons, dans l'ordre d'affichage.
NOMS_BOUTONS = (
    "bridage_mere", "coupe_mere", "position_mere",
    "bridage_fille", "coupe_fille", "position_fille",
    "acquittement",
)


def _actif(octet: int, bit: int, actif_bas: bool) -> bool:
    niveau_haut = bool(octet & (1 << bit))
    return not niveau_haut if actif_bas else niveau_haut


class Filtre:
    """Anti-rebond par temps de stabilité, non bloquant.

    brut        : dernière lecture, sans filtrage
    consecutifs : nombre de lectures brutes actives consécutives
    stable      : valeur retenue après `delai_s` sans changement
    front       : True pendant UN seul tour, quand `stable` passe à actif
    """

    def __init__(self, delai_s: float) -> None:
        self._delai = delai_s
        self._depuis = 0.0
        self._initialise = False
        self.brut = False
        self.consecutifs = 0
        self.stable = False
        self.front = False

    def maj(self, actif: bool, maintenant: float) -> None:
        self.front = False
        self.consecutifs = self.consecutifs + 1 if actif else 0
        if not self._initialise:
            # Première lecture : elle devient l'état stable, SANS front. Un
            # bouton enfoncé au démarrage doit être relâché puis ré-appuyé.
            self.brut = self.stable = actif
            self._depuis = maintenant
            self._initialise = True
            return
        if actif != self.brut:
            self.brut = actif
            self._depuis = maintenant
        elif actif != self.stable and maintenant - self._depuis >= self._delai:
            self.stable = actif
            self.front = actif


class Entrees:
    """Les 7 boutons et les 4 fins de course, rafraîchis une fois par tour."""

    def __init__(self, mcp_relais: Mcp23017, mcp_entrees: Mcp23017) -> None:
        self._mcp_relais = mcp_relais
        self._mcp_entrees = mcp_entrees

        # nom → (octet source, bit)
        self._cablage_boutons = {
            "bridage_mere": ("0x24_B", cfg.BTN_BRIDAGE_MERE),
            "coupe_mere": ("0x24_B", cfg.BTN_COUPE_MERE),
            "position_mere": ("0x24_B", cfg.BTN_POSITION_MERE),
            "bridage_fille": ("0x24_B", cfg.BTN_BRIDAGE_FILLE),
            "coupe_fille": ("0x24_B", cfg.BTN_COUPE_FILLE),
            "position_fille": ("0x24_B", cfg.BTN_POSITION_FILLE),
            "acquittement": ("0x26_B", cfg.BTN_ACQUITTEMENT),
        }
        # (poste, position) → bit du port A du 0x26
        self._cablage_capteurs = {
            (cfg.POSTE_MERE, cfg.POSITION_COUPE): cfg.CAP_MERE_COUPE,
            (cfg.POSTE_MERE, cfg.POSITION_LIGATURAGE): cfg.CAP_MERE_LIGATURAGE,
            (cfg.POSTE_FILLE, cfg.POSITION_COUPE): cfg.CAP_FILLE_COUPE,
            (cfg.POSTE_FILLE, cfg.POSITION_LIGATURAGE): cfg.CAP_FILLE_LIGATURAGE,
        }

        self.boutons = {nom: Filtre(cfg.ANTI_REBOND_BOUTON_S) for nom in NOMS_BOUTONS}
        self.capteurs = {cle: Filtre(cfg.ANTI_REBOND_CAPTEUR_S) for cle in self._cablage_capteurs}
        # Derniers octets bruts lus — affichés par les scripts de test.
        self.octets = {"0x24_B": 0, "0x26_A": 0, "0x26_B": 0}

    def rafraichir(self, maintenant: float) -> None:
        """Deux transactions I2C : 0x26 (A+B en bloc) puis 0x24 port B."""
        # Les fins de course d'abord : ce sont elles qui arrêtent les moteurs.
        octet_26a, octet_26b = self._mcp_entrees.lire_ports()
        octet_24b = self._mcp_relais.lire_port(PORT_B)
        self.octets = {"0x24_B": octet_24b, "0x26_A": octet_26a, "0x26_B": octet_26b}

        for cle, bit in self._cablage_capteurs.items():
            self.capteurs[cle].maj(_actif(octet_26a, bit, cfg.CAPTEURS_ACTIFS_BAS), maintenant)
        for nom, (source, bit) in self._cablage_boutons.items():
            self.boutons[nom].maj(_actif(self.octets[source], bit, cfg.BOUTONS_ACTIFS_BAS), maintenant)

    def appui(self, nom: str) -> bool:
        """True pendant un seul tour, au front d'appui stabilisé."""
        return self.boutons[nom].front

    def capteur(self, poste: str, position: str) -> Filtre:
        return self.capteurs[(poste, position)]
