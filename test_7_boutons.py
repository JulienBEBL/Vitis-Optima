"""
test_7_boutons.py — 3 boutons sur MCP2 (0x26) port B
======================================================
GPB0 = CYCLE, GPB1 = VALIDATION, GPB2 = INIT
Appuie sur chaque bouton pour voir. Ctrl+C pour quitter.
"""
import smbus2
import time

MCP2_ADDR  = 0x26
REG_IODIRB = 0x01
REG_GPPUB  = 0x0D
REG_GPIOB  = 0x13

BIT_CYCLE = 0
BIT_VALID = 1
BIT_INIT  = 2

bus = smbus2.SMBus(1)
bus.write_byte_data(MCP2_ADDR, REG_IODIRB, 0xFF)
bus.write_byte_data(MCP2_ADDR, REG_GPPUB,  0xFF)

print("=" * 40)
print("  TEST 7 — BOUTONS (MCP2 port B)")
print("=" * 40)
print("\n  Appuie sur chaque bouton. Ctrl+C pour quitter.\n")

vu = {"CYCLE": False, "VALID": False, "INIT": False}

try:
    while True:
        raw = bus.read_byte_data(MCP2_ADDR, REG_GPIOB)

        cy = not bool(raw & (1 << BIT_CYCLE))
        va = not bool(raw & (1 << BIT_VALID))
        ini = not bool(raw & (1 << BIT_INIT))

        if cy: vu["CYCLE"] = True
        if va: vu["VALID"] = True
        if ini: vu["INIT"] = True

        print(
            f"\r  CYCLE: {'██' if cy else '··'}"
            f"  VALID: {'██' if va else '··'}"
            f"  INIT: {'██' if ini else '··'}",
            end="", flush=True
        )
        time.sleep(0.05)

except KeyboardInterrupt:
    print("\n\n  Résultat :")
    for nom, ok in vu.items():
        print(f"    {nom:6s} : {'✓ détecté' if ok else '✗ jamais appuyé'}")
    print()
finally:
    bus.close()
