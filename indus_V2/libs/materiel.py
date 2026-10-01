# -*- coding: utf-8 -*-
"""
materiel.py — Couche matérielle basse : bus I2C, MCP23017, puce GPIO, buzzer.

Origine :
  BusI2C      ← Clean-and-Protech V4 libs/i2c_bus.py (retry sur OSError)
                et Vitis V1 indus/mcp23017.py (_write / _read)
  Mcp23017    ← Clean-and-Protech V4 libs/mcp23017.py (registres BANK = 0)
                et Vitis V1 indus/mcp23017.py (image du latch, écriture d'octet atomique)
  ouvrir_puce_gpio ← Clean-and-Protech V4 libs/gpio_handle.py
  Buzzer      ← Clean-and-Protech V4 libs/buzzer.py (lgpio.tx_pwm), rendu NON bloquant
  Materiel    ← Vitis V1 indus/vitis_optima.py (chemin d'arrêt unique du `finally`)

Épuré : pas d'exceptions typées (toute erreur de bus est un OSError, et un
OSError est un défaut D6 — rien d'autre à distinguer), pas de scan de bus, pas
d'accès bit à bit par lecture-modification-écriture sur le bus.
"""

from __future__ import annotations

import collections
import logging
import time

import lgpio
from smbus2 import SMBus

import config as cfg

log = logging.getLogger("vitis")

# Registres MCP23017, mode BANK = 0 : les registres A et B sont consécutifs, ce
# qui permet de lire GPIOA puis GPIOB en une seule transaction.
_IODIRA = 0x00
_IOCON = 0x0A
_GPPUA = 0x0C
_GPIOA = 0x12
_OLATA = 0x14

PORT_A = 0
PORT_B = 1

# Les 8 ENA du 0x25 à « libre ». Les drivers 3..8 ne sont pas utilisés : ils
# restent libres en permanence.
ENA_TOUS_LIBRES = 0xFF if cfg.ENA_MOTEUR_LIBRE else 0x00


# ═══════════════════════════════════════════════════════════════════════════
#  BUS I2C
# ═══════════════════════════════════════════════════════════════════════════

class BusI2C:
    """Accès SMBus avec nouvelles tentatives bornées sur OSError.

    Propriétaire unique : la boucle principale. Les threads d'impulsions ne
    font jamais d'I2C.
    """

    def __init__(self, numero: int) -> None:
        self._smbus = SMBus(numero)

    def _essayer(self, operation, adresse: int, registre: int):
        for tentative in range(cfg.I2C_RETRIES + 1):
            try:
                return operation()
            except OSError as erreur:
                if tentative == cfg.I2C_RETRIES:
                    raise OSError(f"I2C 0x{adresse:02X} registre 0x{registre:02X} : {erreur}") from erreur
                time.sleep(cfg.I2C_RETRY_DELAY_S)

    def ecrire(self, adresse: int, registre: int, valeur: int) -> None:
        self._essayer(lambda: self._smbus.write_byte_data(adresse, registre, valeur), adresse, registre)

    def lire(self, adresse: int, registre: int) -> int:
        return self._essayer(lambda: self._smbus.read_byte_data(adresse, registre), adresse, registre)

    def lire_bloc(self, adresse: int, registre: int, nombre: int) -> list[int]:
        return self._essayer(lambda: self._smbus.read_i2c_block_data(adresse, registre, nombre),
                             adresse, registre)

    def fermer(self) -> None:
        self._smbus.close()


# ═══════════════════════════════════════════════════════════════════════════
#  MCP23017
# ═══════════════════════════════════════════════════════════════════════════

class Mcp23017:
    """Un MCP23017 et l'image logicielle de ses deux latchs de sortie.

    Une sortie s'écrit toujours par octet complet, calculé depuis l'image :
    jamais de lecture-modification-écriture sur le bus, donc un état de sortie
    est appliqué de façon atomique.
    """

    def __init__(self, bus: BusI2C, adresse: int, iodir: tuple[int, int],
                 gppu: tuple[int, int], olat_initial: tuple[int, int]) -> None:
        self.bus = bus
        self.adresse = adresse
        self._iodir = iodir
        self._gppu = gppu
        self._olat = list(olat_initial)

    def configurer(self) -> None:
        """(Re)configure le composant. Sert au démarrage et après une perte de config.

        L'ordre compte : le latch reçoit sa valeur AVANT que le port passe en
        sortie, pour qu'aucune sortie ne prenne un état transitoire.
        """
        self.bus.ecrire(self.adresse, _IOCON, 0x00)   # BANK = 0, lecture séquentielle active
        for port in (PORT_A, PORT_B):
            self.bus.ecrire(self.adresse, _OLATA + port, self._olat[port])
            self.bus.ecrire(self.adresse, _GPPUA + port, self._gppu[port])
            self.bus.ecrire(self.adresse, _IODIRA + port, self._iodir[port])

    def ecrire_port(self, port: int, valeur: int) -> None:
        """Écrit un port complet. L'image n'est mise à jour qu'après succès :
        une écriture ratée sera donc retentée par qui compare l'image."""
        valeur &= 0xFF
        self.bus.ecrire(self.adresse, _OLATA + port, valeur)
        self._olat[port] = valeur

    def image(self, port: int) -> int:
        """Dernière valeur écrite avec succès sur le port."""
        return self._olat[port]

    def lire_port(self, port: int) -> int:
        return self.bus.lire(self.adresse, _GPIOA + port)

    def lire_ports(self) -> tuple[int, int]:
        """GPIOA et GPIOB en UNE transaction : les deux octets datent du même instant."""
        a, b = self.bus.lire_bloc(self.adresse, _GPIOA, 2)
        return a, b

    def ecarts_config(self) -> list[str]:
        """Relit IODIR, GPPU et les latchs de sortie ; renvoie les écarts constatés."""
        ecarts = []
        iodir = self.bus.lire_bloc(self.adresse, _IODIRA, 2)
        gppu = self.bus.lire_bloc(self.adresse, _GPPUA, 2)
        olat = self.bus.lire_bloc(self.adresse, _OLATA, 2)
        for port, nom in ((PORT_A, "A"), (PORT_B, "B")):
            if iodir[port] != self._iodir[port]:
                ecarts.append(f"IODIR{nom}=0x{iodir[port]:02X} au lieu de 0x{self._iodir[port]:02X}")
            if gppu[port] != self._gppu[port]:
                ecarts.append(f"GPPU{nom}=0x{gppu[port]:02X} au lieu de 0x{self._gppu[port]:02X}")
            sorties = ~self._iodir[port] & 0xFF
            if (olat[port] & sorties) != (self._olat[port] & sorties):
                ecarts.append(f"OLAT{nom}=0x{olat[port]:02X} au lieu de 0x{self._olat[port]:02X}")
        return ecarts


# ═══════════════════════════════════════════════════════════════════════════
#  PUCE GPIO
# ═══════════════════════════════════════════════════════════════════════════

def ouvrir_puce_gpio() -> int:
    """Ouvre la puce RP1 et renvoie son handle lgpio.

    Seule une puce dont le libellé contient GPIO_CHIP_LIBELLE est retenue :
    selon le noyau, gpiochip0 est soit le RP1, soit un autre contrôleur.
    """
    for numero in cfg.GPIO_CHIP_CANDIDATS:
        try:
            puce = lgpio.gpiochip_open(numero)
        except Exception:                              # noqa: BLE001 — puce absente
            continue
        try:
            infos = lgpio.gpio_get_chip_info(puce)
        except Exception:                              # noqa: BLE001
            infos = ()
        if any(cfg.GPIO_CHIP_LIBELLE in str(champ).lower() for champ in infos):
            log.info("GPIO : gpiochip%d retenu (%s)", numero, infos)
            return puce
        lgpio.gpiochip_close(puce)
    raise RuntimeError(f"aucune puce GPIO « {cfg.GPIO_CHIP_LIBELLE} » parmi gpiochip"
                       f"{cfg.GPIO_CHIP_CANDIDATS} — vérifier le noyau (ls /dev/gpiochip*)")


# ═══════════════════════════════════════════════════════════════════════════
#  BUZZER
# ═══════════════════════════════════════════════════════════════════════════

class Buzzer:
    """Buzzer passif en PWM, non bloquant.

    Les bips sont une file de segments (son / silence, durée) que la boucle
    principale fait avancer par avancer(). Aucune attente, jamais. Une erreur
    lgpio désactive le buzzer sans rien interrompre d'autre.
    """

    def __init__(self, puce: int) -> None:
        self._puce = puce
        self._actif = cfg.BUZZER_ACTIF
        self._segments: collections.deque = collections.deque()
        self._fin_segment = 0.0
        self._son = False
        if self._actif:
            try:
                lgpio.gpio_claim_output(puce, cfg.BUZZER_GPIO, 0)
            except Exception as erreur:                # noqa: BLE001
                log.warning("buzzer désactivé : %s", erreur)
                self._actif = False

    def bip_court(self) -> None:
        self._jouer([(True, cfg.BIP_COURT_S), (False, cfg.BIP_PAUSE_S)])

    def double_bip(self) -> None:
        self._jouer([(True, cfg.BIP_COURT_S), (False, cfg.BIP_PAUSE_S),
                     (True, cfg.BIP_COURT_S), (False, cfg.BIP_PAUSE_S)])

    def bip_refus(self) -> None:
        self._jouer([(True, cfg.BIP_REFUS_S), (False, cfg.BIP_PAUSE_S)])

    def bip_defaut(self) -> None:
        # Prioritaire : le défaut ne doit pas attendre la fin des bips en file.
        self._segments.clear()
        self._fin_segment = 0.0
        self._jouer([(True, cfg.BIP_DEFAUT_S), (False, cfg.BIP_PAUSE_S)])

    def _jouer(self, segments) -> None:
        if self._actif and len(self._segments) < cfg.BUZZER_FILE_MAX_SEGMENTS:
            self._segments.extend(segments)

    def avancer(self, maintenant: float) -> None:
        if not self._actif or maintenant < self._fin_segment:
            return
        if self._segments:
            son, duree = self._segments.popleft()
            self._appliquer(son)
            self._fin_segment = maintenant + duree
        elif self._son:
            self._appliquer(False)

    def _appliquer(self, son: bool) -> None:
        try:
            lgpio.tx_pwm(self._puce, cfg.BUZZER_GPIO, cfg.BUZZER_FREQ_HZ,
                         cfg.BUZZER_PUISSANCE_PCT if son else 0)
            self._son = son
        except Exception as erreur:                    # noqa: BLE001
            log.warning("buzzer désactivé : %s", erreur)
            self._actif = False

    def couper(self) -> None:
        self._segments.clear()
        try:
            lgpio.tx_pwm(self._puce, cfg.BUZZER_GPIO, cfg.BUZZER_FREQ_HZ, 0)
            lgpio.gpio_write(self._puce, cfg.BUZZER_GPIO, 0)
            lgpio.gpio_free(self._puce, cfg.BUZZER_GPIO)
        except Exception:                              # noqa: BLE001 — arrêt, rien à sauver
            pass
        self._actif = False


# ═══════════════════════════════════════════════════════════════════════════
#  ENSEMBLE DU MATÉRIEL
# ═══════════════════════════════════════════════════════════════════════════

class Materiel:
    """Ouvre les trois MCP et la puce GPIO, et porte le chemin d'arrêt sûr.

    Utilisé à l'identique par main.py et par les scripts de tests/ : les tests
    valident donc le vrai code d'accès au matériel.
    """

    def __init__(self) -> None:
        self.bus: BusI2C | None = None
        self.relais: Mcp23017 | None = None
        self.drivers: Mcp23017 | None = None
        self.entrees: Mcp23017 | None = None
        self.puce: int | None = None
        self._broches: list[int] = []

    def ouvrir(self, avec_gpio: bool = True) -> None:
        """Ouvre et configure tout, en laissant chaque sortie dans son état sûr.

        Lève OSError (MCP muet) ou RuntimeError (puce GPIO introuvable).
        """
        self.bus = BusI2C(cfg.I2C_BUS_ID)

        # Le 0x24 en premier : c'est lui qui porte les relais.
        self.relais = Mcp23017(self.bus, cfg.MCP_RELAIS_ADDR, cfg.MCP_RELAIS_IODIR,
                               cfg.MCP_RELAIS_GPPU, (0x00, 0x00))
        self.relais.configurer()

        # Le 0x25 ensuite : jusqu'ici, la pull-down excite les HUIT drivers.
        self.drivers = Mcp23017(self.bus, cfg.MCP_DRIVERS_ADDR, cfg.MCP_DRIVERS_IODIR,
                                cfg.MCP_DRIVERS_GPPU, (0x00, ENA_TOUS_LIBRES))
        self.drivers.configurer()
        log.info("Relais à 0, ENA des 8 drivers à « libre »")

        self.entrees = Mcp23017(self.bus, cfg.MCP_ENTREES_ADDR, cfg.MCP_ENTREES_IODIR,
                                cfg.MCP_ENTREES_GPPU, (0x00, 0x00))
        self.entrees.configurer()

        if avec_gpio:
            self.puce = ouvrir_puce_gpio()
            for broche in (cfg.PUL_MERE, cfg.PUL_FILLE, *cfg.GPIO_RELAIS_LIBRES):
                lgpio.gpio_claim_output(self.puce, broche, 0)
                self._broches.append(broche)

    def mettre_en_securite(self) -> bool:
        """Relais à 0, ENA à « libre », PUL à 0. Chaque étape est tentée même si
        la précédente échoue. Renvoie False si l'une d'elles a échoué."""
        ok = True
        if self.relais is not None:
            try:
                self.relais.ecrire_port(PORT_A, 0x00)
            except OSError as erreur:
                log.error("ATTENTION : relais non remis à 0 (%s)", erreur)
                ok = False
        if self.drivers is not None:
            try:
                self.drivers.ecrire_port(PORT_B, ENA_TOUS_LIBRES)
            except OSError as erreur:
                log.error("ATTENTION : ENA non remis à « libre » (%s)", erreur)
                ok = False
        if self.puce is not None:
            for broche in self._broches:
                try:
                    lgpio.gpio_write(self.puce, broche, 0)
                except Exception as erreur:            # noqa: BLE001
                    log.error("ATTENTION : GPIO %d non remis à 0 (%s)", broche, erreur)
                    ok = False
        return ok

    def fermer(self) -> bool:
        """Mise en sécurité puis libération de tout. Renvoie le résultat de la mise en sécurité."""
        ok = self.mettre_en_securite()
        if self.puce is not None:
            for broche in self._broches:
                try:
                    lgpio.gpio_free(self.puce, broche)
                except Exception:                      # noqa: BLE001
                    pass
            try:
                lgpio.gpiochip_close(self.puce)
            except Exception:                          # noqa: BLE001
                pass
            self.puce = None
        if self.bus is not None:
            self.bus.fermer()
            self.bus = None
        return ok
