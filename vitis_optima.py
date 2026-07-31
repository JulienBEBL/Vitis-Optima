import time      
import sys    
import signal    
import smbus2 
import RPi.GPIO as GPIO  


UTILISER_CAPTEUR = False

# CONFIGURATION MCP

# I2C 
I2C_BUS_ID       = 1       
I2C_RETRIES      = 2          
I2C_RETRY_DELAY  = 0.01

# Adresses MCP23017 
MCP1_ADDR = 0x24
MCP2_ADDR = 0x26

# Registres MCP23017 (BANK=0) 
REG_IODIRA = 0x00
REG_IODIRB = 0x01
REG_GPPUA  = 0x0C
REG_GPPUB  = 0x0D
REG_GPIOA  = 0x12
REG_GPIOB  = 0x13
REG_OLATA  = 0x14
REG_OLATB  = 0x15

# CONFIGURATION RELAIS
BIT_EV1_PRESSE = 2   # GPA2 → EV 5/2 (presse, V1)
BIT_EV2_COUPE  = 3   # GPA3 → EV 3/2 NF (coupe, V2)

# CONFIGURATION INPUTS 
BIT_CAPTEUR_1   = 0   # GPB0 — capteur position haute V2
BIT_BTN_CYCLE   = 2   # GPB2 — BP COUPE
BIT_BTN_VALID   = 3   # GPB3 — BP RÉCUPÉRATION
BIT_BTN_INIT    = 4   # GPB4 — BP INSTALLATION

# CONFIGURATION OUTPUTS 
VOYANT_VERT_GPIO  = 17
VOYANT_ROUGE_GPIO = 27

# Relais 
RELAY_AIR_GPIO1 = 20   # relais EV air pour PRESSE
RELAY_AIR_GPIO2 = 16   # relais EV air pour COUPE

# TEMPS 
TEMPS_SERRAGE    = 10.0
TEMPS_DECOUPE    = 5.0
TEMPS_RETOUR_V2  = 2.0    # temps de retour V2 quand UTILISER_CAPTEUR = False
TIMEOUT_CAPTEUR  = 5.0    # timeout capteur quand UTILISER_CAPTEUR = True
TEMPS_OUVERTURE  = 1.0    # temps d'ouverture presse après EV1 OFF
ANTI_REBOND      = 0.05


# ════════════════════════════════════════════════════════════════════════
# MCP23017 CLASS 
# ════════════════════════════════════════════════════════════════════════

class MCP23017:
    def __init__(self, bus_num, address):
        self.bus = smbus2.SMBus(bus_num)
        self.addr = address

    def _write(self, reg, val):
        for attempt in range(I2C_RETRIES + 1):
            try:
                self.bus.write_byte_data(self.addr, reg, val)
                return
            except OSError:
                if attempt < I2C_RETRIES:
                    time.sleep(I2C_RETRY_DELAY)
                else:
                    raise

    def _read(self, reg):
        for attempt in range(I2C_RETRIES + 1):
            try:
                return self.bus.read_byte_data(self.addr, reg)
            except OSError:
                if attempt < I2C_RETRIES:
                    time.sleep(I2C_RETRY_DELAY)
                else:
                    raise

    def set_pin(self, port, bit, state):
        reg = REG_OLATA if port == "A" else REG_OLATB
        cur = self._read(reg)
        if state:
            cur |= (1 << bit)
        else:
            cur &= ~(1 << bit)
        self._write(reg, cur)

    def read_pin(self, port, bit):
        reg = REG_GPIOA if port == "A" else REG_GPIOB
        return bool(self._read(reg) & (1 << bit))

    def write_port(self, port, val):
        self._write(REG_OLATA if port == "A" else REG_OLATB, val)

    def read_port(self, port):
        return self._read(REG_GPIOA if port == "A" else REG_GPIOB)

    def close(self):
        self.bus.close()


# VARIABLES GLOBALES
mcp1 = None
mcp2 = None


# ════════════════════════════════════════════════════════════════════════
# INITIALISATION
# ════════════════════════════════════════════════════════════════════════

def init_hardware():
    global mcp1, mcp2

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    GPIO.setup(VOYANT_VERT_GPIO,  GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(VOYANT_ROUGE_GPIO, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(RELAY_AIR_GPIO1,   GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(RELAY_AIR_GPIO2,   GPIO.OUT, initial=GPIO.LOW)

    mcp1 = MCP23017(I2C_BUS_ID, MCP1_ADDR)
    mcp1._write(REG_IODIRA, 0x00)
    mcp1._write(REG_IODIRB, 0xFF)
    mcp1._write(REG_GPPUB,  0xFF)
    mcp1._write(REG_OLATA,  0x00)

    mcp2 = MCP23017(I2C_BUS_ID, MCP2_ADDR)
    mcp2._write(REG_IODIRA, 0xFF)
    mcp2._write(REG_IODIRB, 0xFF)
    mcp2._write(REG_GPPUA,  0xFF)
    mcp2._write(REG_GPPUB,  0xFF)

    mode = "CAPTEUR" if UTILISER_CAPTEUR else "TEMPS"
    print(f"[INIT] MCP1 (0x24) + MCP2 (0x26) — mode retour V2 : {mode}")


# ════════════════════════════════════════════════════════════════════════
# SORTIES: DISTRIBUTEURS
# ════════════════════════════════════════════════════════════════════════

def ev1_presse(on):
    mcp1.set_pin("A", BIT_EV1_PRESSE, on)
    print(f"  [EV1] Presse → {'ON' if on else 'OFF'}")

def ev2_coupe(on):
    mcp1.set_pin("A", BIT_EV2_COUPE, on)
    print(f"  [EV2] Coupe  → {'ON' if on else 'OFF'}")

def toutes_ev_off():
    mcp1.write_port("A", 0x00)
    print("  [EV] Toutes OFF")


# ════════════════════════════════════════════════════════════════════════
# SORTIES: VOYANTS
# ════════════════════════════════════════════════════════════════════════

def voyant_vert(on):
    
    GPIO.output(VOYANT_VERT_GPIO, GPIO.HIGH if on else GPIO.LOW)
    print(f"  [VOYANT] Vert  → {'ON' if on else 'OFF'}")

def voyant_rouge(on):
    GPIO.output(VOYANT_ROUGE_GPIO, GPIO.HIGH if on else GPIO.LOW)
    print(f"  [VOYANT] Rouge → {'ON' if on else 'OFF'}")


# ════════════════════════════════════════════════════════════════════════
# SORTIES: RELAIS 
# ════════════════════════════════════════════════════════════════════════

def air1(on):
    """Relais EV air pour PRESSE."""
    GPIO.output(RELAY_AIR_GPIO1, GPIO.HIGH if on else GPIO.LOW)
    print(f"  [AIR1] Presse → {'ON' if on else 'OFF'}")

def air2(on):
    """Relais EV air pour COUPE."""
    GPIO.output(RELAY_AIR_GPIO2, GPIO.HIGH if on else GPIO.LOW)
    print(f"  [AIR2] Coupe  → {'ON' if on else 'OFF'}")


# ════════════════════════════════════════════════════════════════════════
# ENTRÉES
# ════════════════════════════════════════════════════════════════════════

def v2_en_haut():
    """True = V2 rétracté (lame en haut, capteur activé)."""
    return not mcp2.read_pin("B", BIT_CAPTEUR_1)

def btn_cycle():
    return not mcp2.read_pin("B", BIT_BTN_CYCLE)

def btn_valid():
    return not mcp2.read_pin("B", BIT_BTN_VALID)

def btn_init():
    return not mcp2.read_pin("B", BIT_BTN_INIT)


# ════════════════════════════════════════════════════════════════════════
# SÉCURITÉ + DÉFAUT
# ════════════════════════════════════════════════════════════════════════

def arret_securite():
    """Coupe tout immédiatement."""
    toutes_ev_off()
    GPIO.output(RELAY_AIR_GPIO1, GPIO.LOW)
    GPIO.output(RELAY_AIR_GPIO2, GPIO.LOW)
    GPIO.output(VOYANT_VERT_GPIO, GPIO.LOW)
    GPIO.output(VOYANT_ROUGE_GPIO, GPIO.LOW)
    print("  [SÉCURITÉ] Tout OFF")


def signaler_defaut(message):
    """
    Problème pendant le cycle :
      1. Coupe tous les actionneurs
      2. Allume le voyant rouge
      3. Attend que l'opérateur appuie sur INIT pour acquitter
    """
    print(f"\n  *** DÉFAUT : {message} ***")

    toutes_ev_off()
    GPIO.output(RELAY_AIR_GPIO1, GPIO.LOW)
    GPIO.output(RELAY_AIR_GPIO2, GPIO.LOW)
    voyant_rouge(True)
    voyant_vert(False)

    print("  → Appuyez sur INIT pour acquitter")

    while True:
        if btn_init():
            time.sleep(ANTI_REBOND)
            if btn_init():
                while btn_init():
                    time.sleep(0.01)
                voyant_rouge(False)
                print("  → Défaut acquitté")
                return
        time.sleep(0.01)


def cleanup():
    arret_securite()
    if mcp1: mcp1.close()
    if mcp2: mcp2.close()
    GPIO.cleanup()
    print("ARRET COMPLET")


# ════════════════════════════════════════════════════════════════════════
# LOGIQUE DE LA MACHINE 
# ════════════════════════════════════════════════════════════════════════

def etat_repos():
    """
    REPOS : EV1 OFF, EV2 OFF, air ON, voyant vert ON.
    """
    print("\n" + "=" * 60)
    print("  ÉTAT 0 — REPOS")
    print("=" * 60)

    toutes_ev_off()
    air1(True)
    air2(True)
    voyant_vert(True)
    voyant_rouge(False)

    # Si le capteur est activé, vérifier que V2 est en haut
    if UTILISER_CAPTEUR and not v2_en_haut():
        print("  [ATTENTION] V2 pas en position haute — attente...")
        t0 = time.time()
        while not v2_en_haut():
            if time.time() - t0 > TIMEOUT_CAPTEUR:
                signaler_defaut("V2 bloqué — vérifier vérin / air / capteur")
                return False
            time.sleep(0.01)
        print("  → V2 OK")

    print("  Placer les branches puis appuyez sur CYCLE")
    return True


# ─────────────────────────────────────────────────────────────────────

def attendre_cycle():
    """Attend BP CYCLE."""
    while True:
        if btn_cycle():
            time.sleep(ANTI_REBOND)
            if btn_cycle():
                print("  → Démarrage !")
                while btn_cycle():
                    time.sleep(0.01)
                return

        if btn_init():
            time.sleep(ANTI_REBOND)
            if btn_init():
                print("  → Réinit")
                etat_repos()
                while btn_init():
                    time.sleep(0.01)

        time.sleep(0.01)


# ─────────────────────────────────────────────────────────────────────

def etat_serrage():
    """
    SERRAGE : EV1 ON → V1 serre.
    Attend TEMPS_SERRAGE puis attend VALIDATION.
    """
    print("\n" + "-" * 60)
    print("  SERRAGE")
    print("-" * 60)

    ev1_presse(True)
    print(f"  → V1 serre ({TEMPS_SERRAGE}s)...")

    t0 = time.time()
    while time.time() - t0 < TEMPS_SERRAGE:
        if btn_init():
            print("  [ANNULÉ]")
            ev1_presse(False)
            return False
        time.sleep(0.01)

    print("  → Branches serrées")
    print("  → Appuyez sur VALIDATION pour couper")

    while True:
        if btn_valid():
            time.sleep(ANTI_REBOND)
            if btn_valid():
                print("  → Lancement coupe")
                while btn_valid():
                    time.sleep(0.01)
                return True

        if btn_init():
            time.sleep(ANTI_REBOND)
            if btn_init():
                print("  [ANNULÉ] — relâchement presse")
                ev1_presse(False)
                while btn_init():
                    time.sleep(0.01)
                return False

        time.sleep(0.01)


# ─────────────────────────────────────────────────────────────────────

def etat_decoupe():
    """
    DÉCOUPE : EV1 reste ON, EV2 ON → V2 descend → EV2 OFF → retour V2.

    Si UTILISER_CAPTEUR = True :
      Attend que le capteur détecte V2 revenu. Timeout → défaut.

    Si UTILISER_CAPTEUR = False :
      Attend TEMPS_RETOUR_V2 secondes et considère que V2 est revenu.
    """
    print("\n" + "-" * 60)
    print("  DÉCOUPE")
    print("-" * 60)

    # Phase 1 : V2 descend (EV2 ON)
    ev2_coupe(True)
    print(f"  → Lame descend ({TEMPS_DECOUPE}s)...")

    t0 = time.time()
    while time.time() - t0 < TEMPS_DECOUPE:
        if btn_init():
            print("  [ANNULÉ]")
            toutes_ev_off()
            return False
        time.sleep(0.01)

    # Phase 2 : V2 remonte (EV2 OFF, ressort de rappel)
    ev2_coupe(False)
    print("  → EV2 OFF — ressort ramène V2...")

    if UTILISER_CAPTEUR:
        # ── Mode CAPTEUR : attend le signal du capteur ────────────────
        print(f"  → Attente capteur (timeout {TIMEOUT_CAPTEUR}s)...")
        t0 = time.time()
        while True:
            if v2_en_haut():
                print(f"  → V2 revenu en {time.time() - t0:.2f}s — coupe finie !")
                return True

            if time.time() - t0 > TIMEOUT_CAPTEUR:
                ev1_presse(False)
                signaler_defaut(
                    f"V2 pas revenu après {TIMEOUT_CAPTEUR}s — "
                    "vérifier ressort / pression / capteur"
                )
                return False

            if btn_init():
                print("  [ANNULÉ]")
                ev1_presse(False)
                return False

            time.sleep(0.01)
    else:
        # ── Mode TEMPS : attend un temps fixe, pas de capteur ─────────
        print(f"  → Attente retour V2 ({TEMPS_RETOUR_V2}s) — pas de capteur")
        t0 = time.time()
        while time.time() - t0 < TEMPS_RETOUR_V2:
            if btn_init():
                print("  [ANNULÉ]")
                ev1_presse(False)
                return False
            time.sleep(0.01)
        print("  → Temps écoulé — coupe considérée finie")
        return True


# ─────────────────────────────────────────────────────────────────────

def etat_fin():
    """
    FIN : EV1 OFF → presse s'ouvre.
    Attend INIT pour un nouveau cycle.
    """
    print("\n" + "-" * 60)
    print("  FIN DE CYCLE")
    print("-" * 60)

    ev1_presse(False)
    print(f"  → Presse s'ouvre ({TEMPS_OUVERTURE}s)...")
    time.sleep(TEMPS_OUVERTURE)

    voyant_vert(False)
    print("  → Branches libérées — CYCLE TERMINÉ")
    print("  → Retirez les branches puis appuyez sur INIT pour un nouveau cycle")

    while True:
        if btn_init():
            time.sleep(ANTI_REBOND)
            if btn_init():
                print("  → Nouveau cycle demandé")
                while btn_init():
                    time.sleep(0.01)
                return
        time.sleep(0.01)



# ════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════

def handler_sigint(sig, frame):
    print("\n\n[ARRÊT] Ctrl+C")
    cleanup()
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, handler_sigint)

    try:
        init_hardware()
    except Exception as e:
        print(f"[ERREUR] {e}")
        print(f"  → sudo i2cdetect -y 1")
        print(f"  → MCP1=0x{MCP1_ADDR:02X}, MCP2=0x{MCP2_ADDR:02X}")
        sys.exit(1)

    cycles = 0

    try:
        while True:
            ok = etat_repos()
            if not ok:
                continue

            attendre_cycle()

            if not etat_serrage():
                continue

            if not etat_decoupe():
                continue

            etat_fin()

            cycles += 1
            print(f"\n  ✓ Cycles : {cycles}\n")

    except Exception as e:
        print(f"\n[ERREUR] {e}")
        arret_securite()
        raise

    finally:
        cleanup()


if __name__ == "__main__":
    main()
