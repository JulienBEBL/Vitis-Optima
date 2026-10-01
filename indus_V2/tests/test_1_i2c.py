# -*- coding: utf-8 -*-
"""
test_1_i2c.py — Les trois MCP23017 répondent et gardent leur configuration.

Aucun mouvement, aucune sortie activée. Au contraire : ce test met tout en
état sûr (relais à 0, ENA des 8 drivers à « libre »).

    python3 tests/test_1_i2c.py

Résultat attendu : trois lignes « ✓ », puis « configuration conforme » pour
chaque MCP.
"""

import _commun
from _commun import cfg, titre
from libs.materiel import BusI2C

titre("TEST 1 — BUS I2C ET MCP23017")

bus = BusI2C(cfg.I2C_BUS_ID)
manquants = 0
for nom, adresse in (("relais + boutons", cfg.MCP_RELAIS_ADDR),
                     ("DIR + ENA drivers", cfg.MCP_DRIVERS_ADDR),
                     ("fins de course + acquittement", cfg.MCP_ENTREES_ADDR)):
    try:
        bus.lire(adresse, 0x00)
        print(f"  ✓ 0x{adresse:02X}  {nom}")
    except OSError as erreur:
        print(f"  ✗ 0x{adresse:02X}  {nom} — ne répond pas ({erreur})")
        manquants += 1
bus.fermer()

if manquants:
    print("\n  Vérifier SDA/SCL/VDD/GND et les straps A0/A1/A2.")
    print("  Diagnostic : sudo i2cdetect -y 1\n")
    raise SystemExit(1)

print("\n  Configuration des trois MCP (IOCON, OLAT, GPPU, IODIR)…")
materiel = _commun.ouvrir(avec_gpio=False)
try:
    for mcp in (materiel.relais, materiel.drivers, materiel.entrees):
        ecarts = mcp.ecarts_config()
        if ecarts:
            print(f"  ✗ 0x{mcp.adresse:02X} : {', '.join(ecarts)}")
        else:
            print(f"  ✓ 0x{mcp.adresse:02X} : configuration conforme")
    print("\n  Relais à 0, ENA des 8 drivers à « libre ».\n")
finally:
    materiel.fermer()
