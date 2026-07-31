# -*- coding: utf-8 -*-
"""
mcp23017.py — Pilote I2C minimal pour MCP23017 (mode BANK = 0).

Le composant est utilisé ici avec :
  - le port A entièrement en sorties (relais),
  - le port B entièrement en entrées avec pull-ups internes (boutons).

Le latch de sortie du port A est maintenu dans une image logicielle et écrit
d'un seul bloc. On évite ainsi le read-modify-write sur le bus, et surtout
on garantit qu'un état de sortie est appliqué de façon atomique — condition
nécessaire pour ne jamais alimenter les deux bobines d'un distributeur
bistable en même temps.
"""

import time

import smbus2

# Registres MCP23017, BANK = 0
REG_IODIRA = 0x00   # direction port A (1 = entrée, 0 = sortie)
REG_IODIRB = 0x01   # direction port B
REG_GPPUA  = 0x0C   # pull-ups internes port A
REG_GPPUB  = 0x0D   # pull-ups internes port B
REG_GPIOA  = 0x12   # lecture port A
REG_GPIOB  = 0x13   # lecture port B
REG_OLATA  = 0x14   # latch de sortie port A
REG_OLATB  = 0x15   # latch de sortie port B


class MCP23017:
    """Accès I2C à un MCP23017, avec réessai automatique sur erreur de bus."""

    def __init__(self, bus_num, address, retries=2, retry_delay=0.01):
        self.bus = smbus2.SMBus(bus_num)
        self.addr = address
        self.retries = retries
        self.retry_delay = retry_delay
        self._olata = 0x00          # image logicielle du latch de sortie port A

    # ─────────────────────────────────────────────────────────── bas niveau

    def _write(self, reg, val):
        for tentative in range(self.retries + 1):
            try:
                self.bus.write_byte_data(self.addr, reg, val)
                return
            except OSError:
                if tentative == self.retries:
                    raise
                time.sleep(self.retry_delay)

    def _read(self, reg):
        for tentative in range(self.retries + 1):
            try:
                return self.bus.read_byte_data(self.addr, reg)
            except OSError:
                if tentative == self.retries:
                    raise
                time.sleep(self.retry_delay)

    # ────────────────────────────────────────────────────────── configuration

    def configurer(self):
        """Port A en sorties toutes à 0, port B en entrées avec pull-ups.

        L'ordre compte : le latch est mis à 0 avant de basculer le port en
        sortie, pour qu'aucun relais ne colle brièvement à l'initialisation.
        """
        self._write(REG_OLATA, 0x00)
        self._write(REG_IODIRA, 0x00)
        self._olata = 0x00

        self._write(REG_IODIRB, 0xFF)
        self._write(REG_GPPUB, 0xFF)

    # ────────────────────────────────────────────────────────────── sorties

    def ecrire_sorties(self, valeur):
        """Écrit les 8 bits du port A en une seule transaction."""
        valeur &= 0xFF
        self._write(REG_OLATA, valeur)
        self._olata = valeur

    def sorties(self):
        """Dernière valeur écrite sur le port A."""
        return self._olata

    # ────────────────────────────────────────────────────────────── entrées

    def lire_entrees(self):
        """Lit les 8 bits du port B."""
        return self._read(REG_GPIOB)

    # ─────────────────────────────────────────────────────────────── divers

    def close(self):
        self.bus.close()
