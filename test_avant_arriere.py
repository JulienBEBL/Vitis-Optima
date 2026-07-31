"""
test_avant_arriere.py — Chambre avant et arrière en alternance
================================================================
Quand avant ON → arrière OFF (V2 descend)
Quand arrière ON → avant OFF (V2 remonte)
Boucle 5 fois puis arrête. Ctrl+C pour arrêter avant.

  GPA3 (bit 3) = chambre avant  = V2 descend
  GPA4 (bit 4) = chambre arrière = V2 remonte
"""
import smbus2
import time

MCP1_ADDR  = 0x24
REG_IODIRA = 0x00
REG_OLATA  = 0x14

BIT_AVANT   = 3
BIT_ARRIERE = 4

bus = smbus2.SMBus(1)
bus.write_byte_data(MCP1_ADDR, REG_IODIRA, 0x00)
bus.write_byte_data(MCP1_ADDR, REG_OLATA, 0x00)

print("=" * 50)
print("  TEST — AVANT / ARRIÈRE EN ALTERNANCE")
print("=" * 50)

try:
    for i in range(5):
        # AVANT ON, ARRIÈRE OFF → V2 descend
        bus.write_byte_data(MCP1_ADDR, REG_OLATA, 1 << BIT_AVANT)
        print(f"\n  [{i+1}/5] AVANT ON  — ARRIÈRE OFF  → V2 descend")
        time.sleep(2)

        # AVANT OFF, ARRIÈRE ON → V2 remonte
        bus.write_byte_data(MCP1_ADDR, REG_OLATA, 1 << BIT_ARRIERE)
        print(f"  [{i+1}/5] AVANT OFF — ARRIÈRE ON   → V2 remonte")
        time.sleep(2)

    # Tout OFF
    bus.write_byte_data(MCP1_ADDR, REG_OLATA, 0x00)
    print("\n  → Tout OFF")
    print("  → TEST OK\n")

except KeyboardInterrupt:
    print("\n\n  Arrêt")
    bus.write_byte_data(MCP1_ADDR, REG_OLATA, 0x00)
finally:
    bus.close()
