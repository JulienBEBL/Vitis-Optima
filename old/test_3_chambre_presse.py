import smbus2
import time

MCP1_ADDR  = 0x24
REG_IODIRA = 0x00
REG_OLATA  = 0x14
BIT = 2   # GPA2

bus = smbus2.SMBus(1)
bus.write_byte_data(MCP1_ADDR, REG_IODIRA, 0x00)
bus.write_byte_data(MCP1_ADDR, REG_OLATA, 0x00)


try:
    print("\n  → R_LED presse ON (3s) — écoute le clic...")
    bus.write_byte_data(MCP1_ADDR, REG_OLATA, 1 << BIT)   # 0b00000100
    time.sleep(3)

    print("  → R_LED presse OFF")
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
