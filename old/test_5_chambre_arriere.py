"""
test_5_chambre_arriere.py — R_LED coupe arrière : MCP1 GPA4 (bit 4)
=====================================================================
Chambre arrière du vérin double effet — V2 remonte.
"""
import smbus2
import time

MCP1_ADDR  = 0x24
REG_IODIRA = 0x00
REG_OLATA  = 0x14
BIT = 4   # GPA4

bus = smbus2.SMBus(1)
bus.write_byte_data(MCP1_ADDR, REG_IODIRA, 0x00)
bus.write_byte_data(MCP1_ADDR, REG_OLATA, 0x00)

print("=" * 40)
print("  TEST 5 — CHAMBRE ARRIÈRE (GPA4)")
print("=" * 40)

try:
    print("\n  → R_LED coupe arrière ON (3s) — V2 remonte...")
    bus.write_byte_data(MCP1_ADDR, REG_OLATA, 1 << BIT)   # 0b00010000
    time.sleep(3)

    print("  → R_LED coupe arrière OFF")
    bus.write_byte_data(MCP1_ADDR, REG_OLATA, 0x00)
    time.sleep(1)

    print("  → 3 clics rapides...")
    for _ in range(3):
        bus.write_byte_data(MCP1_ADDR, REG_OLATA, 1 << BIT)
        time.sleep(0.5)
        bus.write_byte_data(MCP1_ADDR, REG_OLATA, 0x00)
        time.sleep(0.5)

    print("\n  → TEST OK\n")
except KeyboardInterrupt:
    bus.write_byte_data(MCP1_ADDR, REG_OLATA, 0x00)
finally:
    bus.close()
