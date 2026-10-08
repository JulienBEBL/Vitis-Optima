# -*- coding: utf-8 -*-
"""
_commun.py — Outils partagés par les scripts de test. Ce n'est pas un test.

Les tests utilisent le VRAI code de libs/ (Materiel, Entrees, Axe) : ils
valident donc à la fois le câblage et le code d'accès au matériel.
Chaque script remet tout en sécurité en sortant (relais à 0, moteurs libres),
y compris sur Ctrl+C.
"""

import logging
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

import config as cfg                                      # noqa: E402
from libs.materiel import Materiel                         # noqa: E402

logging.basicConfig(level=logging.INFO, format="  · %(message)s")


def titre(texte: str) -> None:
    print()
    print("=" * 64)
    print(f"  {texte}")
    print("=" * 64)


def ouvrir(avec_gpio: bool = False) -> Materiel:
    """Vérifie config.py puis ouvre le matériel en état sûr. Quitte en cas d'échec."""
    try:
        cfg.verifier_config()
    except ValueError as erreur:
        print(f"\n  ERREUR DE CONFIGURATION : {erreur}\n")
        sys.exit(2)
    materiel = Materiel()
    try:
        materiel.ouvrir(avec_gpio=avec_gpio)
    except (OSError, RuntimeError) as erreur:
        print(f"\n  ERREUR : {erreur}")
        print("  → lancer d'abord test_1_i2c.py ; diagnostic : sudo i2cdetect -y 1\n")
        materiel.fermer()
        sys.exit(1)
    return materiel


class _LectureSeule:
    """Les deux MCP d'entrée, ouverts SANS toucher à une seule sortie."""

    def __init__(self, bus, relais, entrees):
        self.bus, self.relais, self.entrees = bus, relais, entrees

    def fermer(self) -> None:
        self.bus.fermer()


def ouvrir_lecture_seule() -> _LectureSeule:
    """Pour les tests d'entrées : ne configure QUE les ports d'entrée (direction
    et pull-ups). Aucun relais, aucun ENA, aucun GPIO n'est écrit, ni à
    l'ouverture ni à la fermeture."""
    from libs.materiel import BusI2C, Mcp23017
    try:
        cfg.verifier_config()
        bus = BusI2C(cfg.I2C_BUS_ID)
        # IODIR = 0x00/0x01, GPPU = 0x0C/0x0D. 0x24 : port B seulement.
        bus.ecrire(cfg.MCP_RELAIS_ADDR, 0x01, 0xFF)
        bus.ecrire(cfg.MCP_RELAIS_ADDR, 0x0D, 0xFF)
        for registre in (0x00, 0x01, 0x0C, 0x0D):
            bus.ecrire(cfg.MCP_ENTREES_ADDR, registre, 0xFF)
    except (ValueError, OSError) as erreur:
        print(f"\n  ERREUR : {erreur}\n  → lancer d'abord test_1_i2c.py\n")
        sys.exit(1)
    relais = Mcp23017(bus, cfg.MCP_RELAIS_ADDR, cfg.MCP_RELAIS_IODIR, cfg.MCP_RELAIS_GPPU, (0, 0))
    entrees = Mcp23017(bus, cfg.MCP_ENTREES_ADDR, cfg.MCP_ENTREES_IODIR, cfg.MCP_ENTREES_GPPU, (0, 0))
    return _LectureSeule(bus, relais, entrees)


def bits(octet: int) -> str:
    """Octet en binaire, bit 7 à gauche : « 7654 3210 »."""
    b = f"{octet:08b}"
    return f"{b[:4]} {b[4:]}"


def voyant(actif: bool) -> str:
    return "██" if actif else "··"


def question(texte: str) -> str:
    return input(f"\n  {texte} ").strip().lower()


def confirmer(texte: str) -> bool:
    return question(f"{texte} [o/n]") == "o"


def attendre_entree(texte: str = "Entrée pour continuer, Ctrl+C pour quitter.") -> None:
    input(f"\n  {texte}")


def deplacer(axe, entrees, poste: str, cible: str, lent: bool, budget: int) -> tuple:
    """Mouvement jusqu'à la fin de course `cible`, arrêt comme le programme
    principal (lectures consécutives, puis surcourse). Moteur libéré à la fin.

    Renvoie (pas au moment de la détection ou None, pas total effectués).
    """
    capteur = entrees.capteur(poste, cible)
    entrees.rafraichir(time.monotonic())
    if capteur.brut:
        print(f"  Fin de course {cible} déjà active : aucun mouvement.")
        return 0, 0
    direction = (cfg.DIR_VERS_LIGATURAGE if cible == cfg.POSITION_LIGATURAGE
                 else cfg.DIR_VERS_COUPE)[poste]
    axe.preparer(direction)
    axe.lancer(budget, lent)
    pas_capteur = None
    try:
        while axe.en_marche:
            entrees.rafraichir(time.monotonic())
            if pas_capteur is None and capteur.consecutifs >= cfg.CAPTEUR_LECTURES_ARRET:
                pas_capteur = axe.pas
                axe.demander_arret_apres(cfg.MOTEUR_SURCOURSE_PAS)
            time.sleep(cfg.PERIODE_BOUCLE_S)
    finally:
        axe.demander_arret()
        axe.attendre_fin(cfg.ARRET_THREAD_MAX_S)
        axe.liberer()
    if axe.erreur is not None:
        raise RuntimeError(f"génération d'impulsions interrompue : {axe.erreur}")
    return pas_capteur, axe.pas


def pas_a_vide(axe, direction: int, nombre: int) -> int:
    """`nombre` pas à vitesse d'approche, SANS surveiller les fins de course."""
    axe.preparer(direction)
    axe.lancer(nombre, lent=True)
    try:
        while axe.en_marche:
            time.sleep(cfg.PERIODE_BOUCLE_S)
    finally:
        axe.demander_arret()
        axe.attendre_fin(cfg.ARRET_THREAD_MAX_S)
        axe.liberer()
    return axe.pas
