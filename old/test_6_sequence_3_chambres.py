"""
test_6_sequence_3_chambres.py — Les 3 chambres en séquence
============================================================
Simule le cycle complet des relais :
  1. Presse ON (GPA2)
  2. Coupe avant ON (GPA3) — V2 descend
  3. Coupe avant OFF + Coupe arrière ON (GPA4) — V2 remonte
  4. Tout OFF
"""
import smbus2
import time

MCP1_ADDR  = 0x24
REG_IODIRA = 0x00
REG_OLATA  = 0x14

BIT_PRESSE  = 2   # GPA2
BIT_AVANT   = 3   # GPA3
BIT_ARRIERE = 4   # GPA4

bus = smbus2.SMBus(1)
bus.write_byte_data(MCP1_ADDR, REG_IODIRA, 0x00)
bus.write_byte_data(MCP1_ADDR, REG_OLATA, 0x00)

def set_bits(*bits):
    """Active seulement les bits listés, éteint les autres."""
    val = 0
    for b in bits:
        val |= (1 << b)
    bus.write_byte_data(MCP1_ADDR, REG_OLATA, val)

print("=" * 40)
print("  TEST 6 — SÉQUENCE 3 CHAMBRES")
print("=" * 40)

try:
    # Étape 1 : presse seule
    print("\n  1. Presse ON (GPA2)")
    set_bits(BIT_PRESSE)
    time.sleep(2)

    # Étape 2 : presse + coupe avant (V2 descend)
    print("  2. Presse ON + Avant ON (GPA2 + GPA3) — V2 descend")
    set_bits(BIT_PRESSE, BIT_AVANT)
    time.sleep(2)

    # Étape 3 : presse + coupe arrière (V2 remonte)
    print("  3. Presse ON + Arrière ON (GPA2 + GPA4) — V2 remonte")
    set_bits(BIT_PRESSE, BIT_ARRIERE)
    time.sleep(2)

    # Étape 4 : presse seule (coupe finie)
    print("  4. Presse ON seule (coupe terminée)")
    set_bits(BIT_PRESSE)
    time.sleep(1)

    # Étape 5 : tout OFF
    print("  5. Tout OFF (presse ouvre)")
    set_bits()
    time.sleep(1)

    print("\n  → SÉQUENCE OK\n")
except KeyboardInterrupt:
    bus.write_byte_data(MCP1_ADDR, REG_OLATA, 0x00)
finally:
    bus.close()
