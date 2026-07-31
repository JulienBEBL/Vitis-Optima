
import RPi.GPIO as GPIO
import time

VOYANT_VERT_GPIO  = 22
VOYANT_ROUGE_GPIO = 17

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(VOYANT_VERT_GPIO,  GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(VOYANT_ROUGE_GPIO, GPIO.OUT, initial=GPIO.LOW)



try:
    print("\n  → VERT ON (2s)...")
    GPIO.output(VOYANT_VERT_GPIO, GPIO.HIGH)
    time.sleep(2)
    GPIO.output(VOYANT_VERT_GPIO, GPIO.LOW)
    time.sleep(0.5)

    print("  → ROUGE ON (2s)...")
    GPIO.output(VOYANT_ROUGE_GPIO, GPIO.HIGH)
    time.sleep(2)
    GPIO.output(VOYANT_ROUGE_GPIO, GPIO.LOW)
    time.sleep(0.5)

    print("  → LES DEUX ON (2s)...")
    GPIO.output(VOYANT_VERT_GPIO, GPIO.HIGH)
    GPIO.output(VOYANT_ROUGE_GPIO, GPIO.HIGH)
    time.sleep(2)

    print("\n  → TEST OK\n")
except KeyboardInterrupt:
    pass
finally:
    GPIO.cleanup()
