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


class CompteursMuets:
    """Remplace libs.journal.Compteurs : les essais ne comptent pas dans etat/compteurs.json."""

    def bouton(self, *_, **__):
        pass

    def actionneur(self, *_, **__):
        pass

    def defaut(self, *_, **__):
        pass

    def sauver(self):
        pass

    def sauver_si_du(self, *_, **__):
        pass


def construire_postes(materiel, noms=None) -> tuple:
    """Le VRAI code des postes (libs/poste.py), sans machine.py : pour les tests
    de mouvement. Les relais ne sont pas
    pilotés (mandrins ouverts, lames hautes). Renvoie (entrees, {nom: Poste}, buzzer)."""
    from libs.entrees import Entrees
    from libs.materiel import Buzzer
    from libs.moteur import Axe, PortsDrivers
    from libs.poste import Poste
    drivers = PortsDrivers(materiel.drivers)
    entrees = Entrees(materiel.relais, materiel.entrees)
    buzzer = Buzzer(materiel.puce)
    broches = {cfg.POSTE_MERE: (cfg.PUL_MERE, cfg.DIR_MERE, cfg.ENA_MERE),
               cfg.POSTE_FILLE: (cfg.PUL_FILLE, cfg.DIR_FILLE, cfg.ENA_FILLE)}
    postes = {}
    for nom in (noms or cfg.POSTES):
        axe = Axe(nom, materiel.puce, *broches[nom], drivers)
        postes[nom] = Poste(nom, axe, entrees, CompteursMuets(), buzzer)
    return entrees, postes, buzzer


def tourner(entrees, postes: dict, condition, delai_s: float, quoi: str, buzzer=None) -> float:
    """Boucle à FREQUENCE_BOUCLE_HZ, comme main.py, jusqu'à `condition()`.

    Lève libs.poste.Defaut comme le programme, et TimeoutError au-delà de
    `delai_s`. Renvoie la durée.
    """
    debut = time.monotonic()
    prochain = debut
    while True:
        maintenant = time.monotonic()
        entrees.rafraichir(maintenant)
        for poste in postes.values():
            poste.avancer(maintenant)
        if buzzer is not None:
            buzzer.avancer(maintenant)
        if condition():
            return maintenant - debut
        if maintenant - debut > delai_s:
            raise TimeoutError(f"{quoi} : pas terminé après {delai_s:.0f} s")
        prochain += cfg.PERIODE_BOUCLE_S
        reste = prochain - time.monotonic()
        if reste > 0:
            time.sleep(reste)
        else:
            prochain = time.monotonic()


def initialiser(entrees, postes: dict, buzzer=None, delai_s: float = 90.0) -> float:
    """Initialisation réelle (deux butées en deux passes, puis centrage) des postes donnés.

    Un poste déjà initialisé est d'abord remis en attente : sinon ACQUITTEMENT
    ne ferait qu'un recentrage."""
    from libs.poste import ATTENTE_ACQUITTEMENT, PRET
    maintenant = time.monotonic()
    entrees.rafraichir(maintenant)
    for _ in range(12):                     # remplir l'anti-rebond des butées
        entrees.rafraichir(time.monotonic())
        time.sleep(cfg.PERIODE_BOUCLE_S)
    for poste in postes.values():
        if poste.etat != ATTENTE_ACQUITTEMENT:
            poste.neutraliser(ATTENTE_ACQUITTEMENT)
            poste.axe.attendre_fin(cfg.ARRET_THREAD_MAX_S)
        poste.acquitter(time.monotonic())
    return tourner(entrees, postes, lambda: all(p.etat == PRET for p in postes.values()),
                   delai_s, "initialisation", buzzer)


def arreter_postes(postes: dict) -> None:
    """Arrêt de sécurité des postes d'un test : moteurs arrêtés puis libres."""
    for poste in postes.values():
        poste.neutraliser()
    for poste in postes.values():
        poste.axe.attendre_fin(cfg.ARRET_THREAD_MAX_S)
        try:
            poste.axe.liberer()
        except OSError:
            pass


def fichier_resultat(prefixe: str):
    """Chemin logs/<prefixe>_<date>_<heure>.txt : les résultats y sont gardés même
    si la fenêtre se ferme (dans Geany, Ctrl+C la ferme)."""
    from pathlib import Path
    return Path(cfg.CHEMIN_JOURNAL).parent / f"{prefixe}_{time.strftime('%Y%m%d_%H%M%S')}.txt"


def enregistrer(chemin, lignes: list) -> None:
    """(Ré)écrit le fichier de résultat. Une erreur d'écriture n'arrête pas le test."""
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    except OSError as erreur:
        print(f"  (résultat non enregistré : {erreur})")
