# -*- coding: utf-8 -*-
"""
entrees.py — Boutons et butées : lecture, anti-rebond, fronts.

Origine : indus V2 libs/entrees.py, lui-même repris de Vitis V1
indus/vitis_optima.py, classe `Boutons` (anti-rebond par temps de stabilité,
non bloquant, une seule lecture I2C par port et par tour).
Changements V3 : 9 boutons sur 3 ports (les 2 ROTATION − sur le 0x26 port A),
butées HORAIRE / ANTIHORAIRE au lieu de COUPE / LIGATURAGE, état brut des
boutons exposé par tenu().

Trois usages du même filtre :
  - APPUI d'un bouton : on agit sur le front du signal STABLE. Un bouton
    maintenu ne produit qu'un seul front, donc ne répète jamais l'action.
  - RELÂCHEMENT d'un bouton de rotation : on arrête le moteur sur le signal
    BRUT (tenu()), sans attendre l'anti-rebond — 50 ms feraient 0,5° de trop.
  - BUTÉE : on ARRÊTE le moteur sur le signal BRUT (lectures consécutives),
    puis on CONFIRME l'arrivée sur le signal stable.
"""

from __future__ import annotations

import config as cfg
from libs.materiel import PORT_B, Mcp23017

# Actions d'un poste, dans l'ordre d'affichage.
BRIDAGE = "bridage"
ROTATION_PLUS = "rotation_plus"
ROTATION_MOINS = "rotation_moins"
COUPE = "coupe"
ACTIONS = (BRIDAGE, ROTATION_PLUS, ROTATION_MOINS, COUPE)

ACQUITTEMENT = "acquittement"

# Noms canoniques des boutons, dans l'ordre d'affichage : « action_poste ».
NOMS_BOUTONS = tuple(f"{action}_{poste}" for poste in cfg.POSTES for action in ACTIONS) + (ACQUITTEMENT,)

# nom → (octet source, bit). L'octet source est la clé de Entrees.octets.
CABLAGE_BOUTONS = {
    f"{BRIDAGE}_{cfg.POSTE_MERE}": ("0x24_B", cfg.BTN_BRIDAGE_MERE),
    f"{ROTATION_PLUS}_{cfg.POSTE_MERE}": ("0x24_B", cfg.BTN_ROTATION_PLUS_MERE),
    f"{ROTATION_MOINS}_{cfg.POSTE_MERE}": ("0x26_A", cfg.BTN_ROTATION_MOINS_MERE),
    f"{COUPE}_{cfg.POSTE_MERE}": ("0x24_B", cfg.BTN_COUPE_MERE),
    f"{BRIDAGE}_{cfg.POSTE_FILLE}": ("0x24_B", cfg.BTN_BRIDAGE_FILLE),
    f"{ROTATION_PLUS}_{cfg.POSTE_FILLE}": ("0x24_B", cfg.BTN_ROTATION_PLUS_FILLE),
    f"{ROTATION_MOINS}_{cfg.POSTE_FILLE}": ("0x26_A", cfg.BTN_ROTATION_MOINS_FILLE),
    f"{COUPE}_{cfg.POSTE_FILLE}": ("0x24_B", cfg.BTN_COUPE_FILLE),
    ACQUITTEMENT: ("0x26_B", cfg.BTN_ACQUITTEMENT),
}

# (poste, sens) → bit du port B du 0x26
CABLAGE_BUTEES = {
    (cfg.POSTE_MERE, cfg.SENS_HORAIRE): cfg.CAP_MERE_HORAIRE,
    (cfg.POSTE_MERE, cfg.SENS_ANTIHORAIRE): cfg.CAP_MERE_ANTIHORAIRE,
    (cfg.POSTE_FILLE, cfg.SENS_HORAIRE): cfg.CAP_FILLE_HORAIRE,
    (cfg.POSTE_FILLE, cfg.SENS_ANTIHORAIRE): cfg.CAP_FILLE_ANTIHORAIRE,
}


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
    """Les 9 boutons et les 4 butées, rafraîchis une fois par tour."""

    def __init__(self, mcp_relais: Mcp23017, mcp_entrees: Mcp23017) -> None:
        self._mcp_relais = mcp_relais
        self._mcp_entrees = mcp_entrees
        self.boutons = {nom: Filtre(cfg.ANTI_REBOND_BOUTON_S) for nom in NOMS_BOUTONS}
        self.butees = {cle: Filtre(cfg.ANTI_REBOND_CAPTEUR_S) for cle in CABLAGE_BUTEES}
        # Derniers octets bruts lus — affichés par les scripts de test.
        self.octets = {"0x24_B": 0, "0x26_A": 0, "0x26_B": 0}

    def rafraichir(self, maintenant: float) -> None:
        """Deux transactions I2C : 0x26 (A+B en bloc) puis 0x24 port B."""
        # Le 0x26 d'abord : il porte les butées, qui arrêtent les moteurs.
        octet_26a, octet_26b = self._mcp_entrees.lire_ports()
        octet_24b = self._mcp_relais.lire_port(PORT_B)
        self.octets = {"0x24_B": octet_24b, "0x26_A": octet_26a, "0x26_B": octet_26b}

        for cle, bit in CABLAGE_BUTEES.items():
            self.butees[cle].maj(_actif(octet_26b, bit, cfg.CAPTEURS_ACTIFS_BAS), maintenant)
        for nom, (source, bit) in CABLAGE_BOUTONS.items():
            self.boutons[nom].maj(_actif(self.octets[source], bit, cfg.BOUTONS_ACTIFS_BAS), maintenant)

    def appui(self, nom: str) -> bool:
        """True pendant un seul tour, au front d'appui stabilisé."""
        return self.boutons[nom].front

    def tenu(self, nom: str) -> bool:
        """Bouton enfoncé à la DERNIÈRE lecture, sans anti-rebond (relâchement d'une rotation)."""
        return self.boutons[nom].brut

    def butee(self, poste: str, sens: str) -> Filtre:
        return self.butees[(poste, sens)]
