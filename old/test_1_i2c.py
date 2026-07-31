
import smbus2

bus = smbus2.SMBus(1)


for name, addr in [("MCP1", 0x24), ("MCP2", 0x26)]:
    try:
        val = bus.read_byte_data(addr, 0x00)
        print(f"  ✓ {name} détecté à 0x{addr:02X} (IODIRA = 0x{val:02X})")
    except OSError:
        print(f"  ✗ {name} PAS trouvé à 0x{addr:02X}")

bus.close()
print("\n  Si un MCP manque → vérifier câblage SDA/SCL/VDD/GND + A0/A1/A2")
print("  Commande utile : sudo i2cdetect -y 1\n")
