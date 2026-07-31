# -*- coding: utf-8 -*-
"""
config.py — Configuration matérielle et temporisations de la machine.

C'EST LE SEUL FICHIER À MODIFIER pour adapter le programme au câblage réel.
Aucun numéro de broche ni aucune durée ne doit apparaître ailleurs.

Câblage PCB v1 (Raspberry Pi 5) :
  - Un unique MCP23017 en 0x24 sur le bus I2C 1.
  - Port A = sorties  → relais → électrovannes.
  - Port B = entrées  → boutons poussoirs (NO vers la masse, pull-ups internes).
  - Aucun GPIO direct de la Raspberry Pi n'est utilisé.
  - L'arrêt d'urgence est câblé en dur et n'est pas vu par le programme.
"""

# ═══════════════════════════════════════════════════════════════════════
#  BUS I2C
# ═══════════════════════════════════════════════════════════════════════

I2C_BUS_ID      = 1        # /dev/i2c-1
MCP_ADDR        = 0x24     # seul composant utilisé (d'autres répondent mais sont ignorés)

I2C_RETRIES     = 2        # nombre de nouvelles tentatives sur erreur I2C
I2C_RETRY_DELAY = 0.01     # délai entre deux tentatives (s)


# ═══════════════════════════════════════════════════════════════════════
#  SORTIES — port A du MCP23017
# ═══════════════════════════════════════════════════════════════════════

# Vérin de COUPE : distributeur monostable, rappel par ressort.
#   bit à 1 = lame sortie / bit à 0 = retour ressort
BIT_EV_COUPE = 2           # GPA2

# Vérin de MISE EN POSITION : distributeur 5/2 BISTABLE, deux bobines.
#   La bobine est maintenue alimentée tant que l'état est actif.
#   Les deux bobines ne sont JAMAIS alimentées en même temps (garanti par le code).
#
# ⚠ SENS À CONFIRMER SUR LA MACHINE.
#   Lance test_avant_arriere.py, regarde dans quel sens part le vérin,
#   et si c'est inversé : échange simplement les deux valeurs ci-dessous.
BIT_POS_DESCENTE = 3       # GPA3 — fait DESCENDRE le vérin de mise en position
BIT_POS_MONTEE   = 4       # GPA4 — fait REMONTER le vérin de mise en position


# ═══════════════════════════════════════════════════════════════════════
#  ENTRÉES — port B du MCP23017
# ═══════════════════════════════════════════════════════════════════════

# ⚠ CORRESPONDANCE À CONFIRMER SUR LA MACHINE.
#   Lance test_7_boutons.py et note quel indicateur s'allume pour chaque
#   bouton physique, puis ajuste les trois valeurs ci-dessous.
BIT_BTN_POSITION = 0       # GPB0 — abaisse le vérin de mise en position
BIT_BTN_COUPE    = 1       # GPB1 — déclenche une coupe
BIT_BTN_RESET    = 2       # GPB2 — coupe OFF + vérin de position en haut

# True  : bouton NO vers la masse + pull-up interne → appui = niveau bas.
# False : appui = niveau haut.
BOUTONS_ACTIFS_BAS = True


# ═══════════════════════════════════════════════════════════════════════
#  TEMPORISATIONS (secondes)
# ═══════════════════════════════════════════════════════════════════════

# Durée d'activation du vérin de coupe après appui sur le bouton COUPE.
# Passé ce délai la sortie retombe et le ressort ramène la lame.
TEMPS_DECOUPE = 0.75

# Temps mort imposé entre la coupure d'une bobine du bistable et
# l'alimentation de l'autre. Garantit qu'elles ne se recouvrent jamais.
TEMPS_INTER_BOBINE = 0.05

# Durée pendant laquelle l'état d'un bouton doit être stable pour être pris
# en compte (anti-rebond).
ANTI_REBOND = 0.05

# Période de la boucle principale. Plus c'est court, plus la machine est
# réactive, mais plus le bus I2C est sollicité.
PERIODE_SCRUTATION = 0.01


# ═══════════════════════════════════════════════════════════════════════
#  SÉCURITÉ ET COMPORTEMENT
# ═══════════════════════════════════════════════════════════════════════

# True  : au démarrage, POSITION et COUPE sont refusés tant qu'un RESET n'a
#         pas été fait. Le distributeur bistable garde son état mécanique
#         hors tension : le programme ignore où se trouve le vérin au
#         lancement, et le RESET est ce qui le remet dans un état connu.
# False : la machine accepte les commandes dès le démarrage.
RESET_REQUIS_AU_DEMARRAGE = True

# True  : le bouton COUPE est ignoré tant que le vérin de mise en position
#         n'est pas descendu. Garde-fou logiciel contre une coupe à vide.
# False : les trois boutons agissent de façon totalement indépendante.
EXIGER_POSITION_AVANT_COUPE = False
