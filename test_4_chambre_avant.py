"""
test_4_chambre_avant.py — R_LED coupe avant : MCP1 GPA3 (bit 3)
=================================================================
Chambre avant du vérin double effet — V2 descend.
"""
import smbus2
import time

MCP1_ADDR  = 0x24
REG_IODIRA = 0x00
REG_OLATA  = 0x14
BIT = 3   # GPA3

bus = smbus2.SMBus(1)
bus.write_byte_data(MCP1_ADDR, REG_IODIRA, 0x00)
bus.write_byte_data(MCP1_ADDR, REG_OLATA, 0x00)

print("=" * 40)
print("  TEST 4 — CHAMBRE AVANT (GPA3)")
print("=" * 40)

try:
    print("\n  → R_LED coupe avant ON (3s) — V2 descend...")
    bus.write_byte_data(MCP1_ADDR, REG_OLATA, 1 << BIT)   # 0b00001000
    time.sleep(3)

    print("  → R_LED coupe avant OFF")
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
