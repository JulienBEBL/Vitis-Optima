#T
import time      
import sys    
import signal    
import smbus2     # communication I2C avec le MCP23017
import RPi.GPIO as GPIO  

# CONFIGURATION MCP

# I2C 
I2C_BUS_ID       = 1       
I2C_RETRIES      = 2          
I2C_RETRY_DELAY  = 0.01       # délai entre tentatives (10 ms)

# Adresses MCP23017 
MCP1_ADDR = 0x24    # port A = LEDs/distributeurs (sorties), port B = boutons PRG (entrées)
MCP2_ADDR = 0x26    # port A = injection AIR (entrées), port B = détection VIC (entrées)
MCP3_ADDR = 0x25    # port A = DIR drivers (sorties), port B = ENA drivers (sorties)

# Registres MCP23017 (BANK=0) 
REG_IODIRA = 0x00   # direction port A (1=entrée, 0=sortie)
REG_IODIRB = 0x01   # direction port B
REG_GPPUA  = 0x0C   # pull-up interne port A
REG_GPPUB  = 0x0D   # pull-up interne port B
REG_GPIOA  = 0x12   # lecture port A
REG_GPIOB  = 0x13   # lecture port B
REG_OLATA  = 0x14   # écriture latch port A
REG_OLATB  = 0x15   # écriture latch port B

# CONFIGURATION RELAIS
# Le relais 
BIT_EV1_PRESSE = 2   # GPA2 to EV 5/2 (presse, V1) ------ GPIO 24  --- OK 
BIT_EV_COUPE_AVANT  = 3   # GPA1 → R_LED2 → relais → EV coupe chambre avant
BIT_EV_COUPE_ARRIERE = 4   # GPA2 → R_LED3 → relais → EV coupe chambre arrière


# CONFIGURATION INPUTS 
# CAPTUREURS 
# BIT_CAPTEUR_1   = 0   # GPB0 (bornier VIC pin 1) ---- ok
# BOUTONS
BIT_BTN_CYCLE   = 0   # BP PRESSE (NO) ---- ok
BIT_BTN_VALID   = 1   # BP COUPE (NO) ---- ok
BIT_BTN_INIT    = 2   # BP INSTALLATION (NO) ---- ok

# CONFIGURATION OUTPUTS 

# Voyants lumineux
VOYANT_VERT_GPIO  = 22   # GPIO17 (pin 11) = PUL_1 → DRIVER1 → voyant vert (prêt)   ----- ok
VOYANT_ROUGE_GPIO = 17   # GPIO27 (pin 13) = PUL_2 → DRIVER2 → voyant rouge (défaut)    ------ ok

# Relais 
# RELAY_AIR_GPIO1   = 20   # GPIO20 (pin 38) → relais R_EV1  -----ok
# RELAY_AIR_GPIO2 = 16   # GPIO16 (pin 36) → relais R_EV2 ---- ok



# TEMPS 
TEMPS_SERRAGE   = 10.0   # durée déploiement V1 (presse)    ---ok 
TEMPS_DECOUPE   = 5.0    # durée V2 poussé (lame)
TEMPS_RETOUR    = 0.5    # rétraction par ressort de rappel
TIMEOUT_VALID   = 1.0   # timeout avant ouverture auto des presses
ANTI_REBOND     = 0.05   # anti-rebond boutons (50 ms)



# MCP23017 CLASS 

class MCP23017:
    """Pilote I2C pour MCP23017 avec retry automatique"""

    def __init__(self, bus_num, address):
        self.bus = smbus2.SMBus(bus_num)
        self.addr = address

    def _write(self, reg, val):
        """Écriture I2C. Réessaie I2C_RETRIES fois si OSError."""
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
        """Lecture I2C. Réessaie I2C_RETRIES fois si OSError"""
        for attempt in range(I2C_RETRIES + 1):
            try:
                return self.bus.read_byte_data(self.addr, reg)
            except OSError:
                if attempt < I2C_RETRIES:
                    time.sleep(I2C_RETRY_DELAY)
                else:
                    raise

    def set_pin(self, port, bit, state):
        """Change 1 bit d'un port (read-modify-write sur le latch)."""
        reg = REG_OLATA if port == "A" else REG_OLATB
        cur = self._read(reg)
        if state:
            cur |= (1 << bit)
        else:
            cur &= ~(1 << bit)
        self._write(reg, cur)

    def read_pin(self, port, bit):
        """Lit 1 bit d'un port. True = HIGH."""
        reg = REG_GPIOA if port == "A" else REG_GPIOB
        return bool(self._read(reg) & (1 << bit))

    def write_port(self, port, val):
        """Écrit 8 bits sur un port."""
        self._write(REG_OLATA if port == "A" else REG_OLATB, val)

    def read_port(self, port):
        """Lit 8 bits d'un port."""
        return self._read(REG_GPIOA if port == "A" else REG_GPIOB)

    def close(self):
        self.bus.close()

#VARIABLES GLOBALES
mcp1 = None           # MCP (0x24) sorties distributeurs
mcp2 = None           # MCP (0x26) entrées capteurs + boutons

# INITIALISATION

def init_hardware():
    """
    Initialise GPIO + MCP1 + MCP2. Toutes sorties OFF
    """
    global mcp1, mcp2

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    # Sorties GPIO 
    GPIO.setup(VOYANT_VERT_GPIO,  GPIO.OUT, initial=GPIO.LOW)   # PUL_8 → DRIVER1
    GPIO.setup(VOYANT_ROUGE_GPIO, GPIO.OUT, initial=GPIO.LOW)   # PUL_7 → DRIVER2
    GPIO.setup(BIT_EV1_PRESSE,    GPIO.OUT, initial=GPIO.LOW)   # relais ev1
    GPIO.setup(BIT_EV_COUPE_AVANT,    GPIO.OUT, initial=GPIO.LOW)   # relais ev2
    GPIO.setup(BIT_EV_COUPE_ARRIERE,    GPIO.OUT, initial=GPIO.LOW)   # relais ev2
    
    # MCP1 (0x24): sorties distributeurs 
    mcp1 = MCP23017(I2C_BUS_ID, MCP1_ADDR)
    mcp1._write(REG_IODIRA, 0x00)    
    mcp1._write(REG_IODIRB, 0xFF)    # port B non utilisé)
    mcp1._write(REG_GPPUB,  0xFF)    
    mcp1._write(REG_OLATA,  0x00)    

    # MCP2 (0x26): entrées capteurs + boutons 
    mcp2 = MCP23017(I2C_BUS_ID, MCP2_ADDR)
    mcp2._write(REG_IODIRA, 0xFF)    # port A non utilisé
    mcp2._write(REG_IODIRB, 0xFF)    
    mcp2._write(REG_GPPUA,  0xFF)    
    mcp2._write(REG_GPPUB,  0xFF)   

    print("[INIT] Matériel initialisé — MCP1 (0x24) + MCP2 (0x26)")
    print("[INIT] Toutes sorties OFF")




    # SORTIES: DISTRIBUTEURS (MCP1 port A → relais → EV)

def ev1_presse(on):
    """
    EV1 (presse / serrage)
    MCP1 → R_LED1 → EV 3/2 mono
    ON = V1 sort (mâchoires serrent). OFF = ressort rétracte.
    """
    mcp1.set_pin("A", BIT_EV1_PRESSE, on)
    print(f"  [EV1] Presse → {'ON' if on else 'OFF'}")


def ev2_coupe(on):
    """
    EV2 (coupe)
    MCP1 → R_LED2 → 24V → EV 5/2 NF
    ON = air pousse V2 (lame descend). OFF = ressort rétracte (EV NF se ferme).
    """
    mcp1.set_pin("A", BIT_EV_COUPE_AVANT, on)
    print(f"  [EV2] Coupe  → {'ON' if on else 'OFF'}")


def ev3_coupe(on):
    """
    EV2 (découpe)
    MCP1 → R_LED3 → 24V → EV 5/2 NF
    ON = air pousse V2 (lame descend). OFF = ressort rétracte (EV NF se ferme).
    """
    mcp1.set_pin("A", BIT_EV_COUPE_ARRIERE, on)
    print(f"  [EV3] Découpe  → {'ON' if on else 'OFF'}")

def toutes_ev_off():
    """ EV1 + EV2 (off pour l'initialisation)."""
    mcp1.write_port("A", 0x00)
    print("  [EV] Toutes OFF")





# SORTIES: VOYANTS LUMINEUX
def voyant_vert(on):
    """
   Machine prête
    """
    GPIO.output(VOYANT_VERT_GPIO, GPIO.HIGH if on else GPIO.LOW)
    print(f"  [VOYANT] Vert  → {'ON' if on else 'OFF'}")


def voyant_rouge(on):
    """
    Défaut / erreur
    """
    GPIO.output(VOYANT_ROUGE_GPIO, GPIO.HIGH if on else GPIO.LOW)
    print(f"  [VOYANT] Rouge → {'ON' if on else 'OFF'}")

# SORTIES: RELAIS 

#def air1(on):
    """
    Relais d'electrovanne 1 pour PRESSE
    """
    #GPIO.output(RELAY_AIR_GPIO, GPIO.HIGH if on else GPIO.LOW)
    #print(f"  [AIR] → {'ON' if on else 'OFF'}")


#def air2(on):
    """
    Relais d'electrovanne 2 pour COUPE
       """
    #GPIO.output(RELAY_AIR_GPIO2, GPIO.HIGH if on else GPIO.LOW)
    #print(f"  [POMPE] → {'ON' if on else 'OFF'}")


# ENTRÉES: CAPTEURS 

#def v2_en_haut():
    """True = V2 rétracté (lame en haut, capteur activé)."""
   # return not mcp2.read_pin("B", BIT_CAPTEUR_1)

# ENTRÉES: BOUTONS 

def btn_cycle():
    """
    Bouton CYCLE 
    """
    return not mcp2.read_pin("B", BIT_BTN_CYCLE)


def btn_valid():
    """
    Bouton VALIDATION (RÉCUPÉRATION) 
    """
    return not mcp2.read_pin("B", BIT_BTN_VALID)


def btn_init():
    """
    Bouton INIT (INSTALLATION) → MCP2 GPB4.
    """
    return not mcp2.read_pin("B", BIT_BTN_INIT)


# SECURITE

def arret_securite():
    """Coupe tout immédiatement"""
    toutes_ev_off()
    GPIO.output(BIT_EV1_PRESSE,    GPIO.OUT, initial=GPIO.LOW)   # relais ev1
    
    GPIO.output(BIT_EV_COUPE_AVANT,    GPIO.OUT, initial=GPIO.LOW)   # relais ev2
    GPIO.output(BIT_EV_COUPE_ARRIERE , GPIO.OUT, initial=GPIO.LOW)    # relais ev2
    GPIO.output(VOYANT_VERT_GPIO, GPIO.LOW)
    GPIO.output(VOYANT_ROUGE_GPIO, GPIO.LOW)
    print("  [SÉCURITÉ] Tout OFF")

def cleanup():
    arret_securite()
    if mcp1: mcp1.close()
    if mcp2: mcp2.close()
    GPIO.cleanup()
    print("ARRET COMPLET")





# -------------------------------------------------------------------------------------------------------------
# LOGIQUE DE LA MACHINE 




def etat_repos():
    """
    EV1 OFF, EV2 OFF. Air ON (prêt). Voyant vert ON.
    L'opérateur place les branches puis appuie sur CYCLE
    """
    print("\n" + "=" * 60)
    print("  ÉTAT 0 — REPOS")
    print("=" * 60)

    toutes_ev_off()
    ev1_presse(False)
    ev2_coupe(False)
    ev3_coupe(False)
    voyant_vert(True)
    voyant_rouge(False)

    print("Placer les branches aprés Appuyez sur CYCLE")

# -------------------------------------------------------------------------------------------------------------

def attendre_cycle():
    """Attend BP CYCLE"""
    while True:
        if btn_cycle():
            time.sleep(ANTI_REBOND)
            if btn_cycle():
                print("démarrage !")
                voyant_vert(True)
                while btn_cycle():
                    time.sleep(0.01)
                return False

        if btn_init():
            time.sleep(ANTI_REBOND)
            if btn_init():
                print("  → Réinit")
                etat_repos()
                while btn_init():
                    time.sleep(0.01)

        time.sleep(0.01)

# -------------------------------------------------------------------------------------------------------------

def etat_serrage():
    """
    SERRAGE (V1)    
    air1 ON → EV1 ON → V1 sort (presse les branches).

    """
    print("\n" + "-" * 60)
    print(" SERRAGE")
    print("-" * 60)

    # Phase 1 : déploiement V1
    ev1_presse(True)
 
    print(f"  → V1 serre ({TEMPS_SERRAGE}s)...")

    t0 = time.time()
    while time.time() - t0 < TEMPS_SERRAGE:
        if btn_init():
            print("  [ANNULÉ]")
            ev1_presse(False)
            return False
        time.sleep(0.01)

    print("Branches serrées")

    # Phase 2 : attente VALIDATION pour lancer la coupe
    print("Appuyez sur VALIDATION pour couper")

    while True:
        if btn_valid():
            time.sleep(ANTI_REBOND)
            if btn_valid():
                print("lancement coupe")
                while btn_valid():
                    time.sleep(0.01)
                return True

        if btn_init():
            time.sleep(ANTI_REBOND)
            if btn_init():
                print("  [ANNULÉ] relâchement presse")
                ev1_presse(False)
                while btn_init():
                    time.sleep(0.01)
                return False

        time.sleep(0.01)



# -------------------------------------------------------------------------------------------------------------

def etat_decoupe():
    """
    DÉCOUPE (V1 + V2)
    EV1 reste ON. EV2 ON → V2 sort (lame descend).
    le CAPTEUR de fin de coupe détecte que V2 a fini sa course.

    """
    print("\n" + "-" * 60)
    print("COUPE")
    print("-" * 60)

    # Phase 1 : V2 descend
    ev2_coupe(True)
    ev3_coupe(False)
    print(f" lame descend ({TEMPS_DECOUPE}s)...")

    t0 = time.time()
    while time.time() - t0 < TEMPS_DECOUPE:
        if btn_init():
            print("  [ANNULÉ]")
            toutes_ev_off()
            return False
        time.sleep(0.01)

    # Phase 2 : V2 remonte (ressort de rappel)
    ev2_coupe(False)
    ev3_coupe(True)
    print("EV2 OFF: ressort ramène V2")

    t0 = time.time()
    while True:
        
        if time.time() - t0 > TEMPS_RETOUR:
            print(f"  [DÉFAUT] V2 pas revenu après {TEMPS_RETOUR}s")
            ev1_presse(False)
            voyant_rouge(True)
            return False

        if btn_init():
            print("[ANNULÉ]")
            ev1_presse(False)
            return False

        time.sleep(0.01)






# -------------------------------------------------------------------------------------------------------------

def etat_fin():
    """
    Coupe terminée, V2 revenu en haut.
    EV1 OFF → presse s'ouvre → branches libérées.
    """
    print("\n" + "-" * 60)
    print("  ÉTAT 3 — FIN")
    print("-" * 60)

    ev1_presse(False)
    voyant_rouge(True)
    print(f" presse s'ouvre ({TIMEOUT_VALID}s)...")
    time.sleep(TIMEOUT_VALID)

    print("Retirez la branche puis appuyez sur INIT pour un nouveau cycle")
    
    while True:
        if btn_init():
            time.sleep(ANTI_REBOND)
            if btn_init():
                print("Nouveau cycle demandé")
                while btn_init():
                    time.sleep(0.01)
                return
        time.sleep(0.01)


# MAIN


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

    try:
        while True:
            etat_repos()              # EV1 OFF, EV2 OFF, voyant vert ON
            attendre_cycle()           # attend BP CYCLE

            if not etat_serrage():    # EV1 ON, attend BP VALIDATION
                continue

            if not etat_decoupe():    # EV2 ON→OFF, attend capteur V2
                continue

            etat_fin()                # EV1 OFF, branches libérées, voyant rouge ON

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




