# -*- coding: utf-8 -*-
"""
config.py — Configuration matérielle et temporisations de la Vitis Optima indus V2.

C'EST LE SEUL FICHIER À MODIFIER pour adapter le programme au câblage réel.
Aucun numéro de broche, aucune durée, aucune adresse ne doit apparaître ailleurs
dans le code. Tout le reste importe ce module (`import config as cfg`).

La logique de pilotage est décrite dans LOGIQUE.md.
La mise en service et les tests sont décrits dans README.md.

═══════════════════════════════════════════════════════════════════════════════
 MACHINE
═══════════════════════════════════════════════════════════════════════════════
Deux postes symétriques — « mère » et « fille ». Chacun possède :
  - 1 EV de BRIDAGE, 1 bobine : bobine coupée = sortie AIR 1 = DÉBRIDÉ
  - 1 EV de COUPE,   1 bobine : bobine coupée = sortie AIR 1 = LAME HAUTE
  - 1 axe NEMA 34 + driver JK-DM860H, entre deux fins de course :
    POSITION_COUPE et POSITION_LIGATURAGE
  - 3 boutons : BRIDAGE, COUPE, POSITION (mise en position pour ligaturage)
Plus 1 bouton ACQUITTEMENT commun et 1 buzzer. Aucun voyant.

Bit relais à 0 = bobine coupée = état sûr. C'est le câblage qui le garantit :
toute sortie du programme remet les relais à 0.

L'arrêt d'urgence est câblé en dur et coupe tout, Raspberry Pi comprise.
Le logiciel ne le voit pas : au réarmement, le programme repart de zéro.

PCB : « indus V1 » de Clean and Protech, 8 emplacements de drivers.
Seuls les drivers 1 (poste mère) et 2 (poste fille) sont utilisés.

═══════════════════════════════════════════════════════════════════════════════
 VALEURS NON CONFIRMÉES — à vérifier avec les scripts de tests/ (voir README.md)
═══════════════════════════════════════════════════════════════════════════════
  ⚠ À CONFIRMER   BTN_* ................ bouton physique ↔ bit          (test_2)
                  CAP_* ................ fin de course ↔ bit            (test_3)
                  CAPTEURS_ACTIFS_BAS .. polarité + repli au débranchement (test_3)
                  EV_* ................. relais ↔ EV, sens de sortie    (test_4)
                  DIR_MERE / DIR_FILLE . câblage DIR inversé du PCB     (test_5)
                  DIR_VERS_COUPE ....... sens de rotation               (test_5)
                  DRIVER_PAS_PAR_TOUR .. LIRE L'ÉTIQUETTE DU DRIVER (table DIP)
  ⚠ À DÉTERMINER  MOTEUR_MAITRE, MOTEUR_COURSE_DEGRES (test_6), MOTEUR_REDUCTION
  ⚠ À AJUSTER     vitesses et accélérations moteur, temporisations pneumatiques,
                  RETARD_SENS_ALLER_S
"""

from __future__ import annotations

import math
from pathlib import Path


# ═══════════════════════════════════════════════════════════════════════════
#  VOCABULAIRE MÉTIER  (chaînes canoniques — définies ici pour éviter la dérive)
# ═══════════════════════════════════════════════════════════════════════════

POSTE_MERE = "mere"
POSTE_FILLE = "fille"
POSTES = (POSTE_MERE, POSTE_FILLE)

POSITION_COUPE = "coupe"
POSITION_LIGATURAGE = "ligaturage"


# ═══════════════════════════════════════════════════════════════════════════
#  BUS I2C
# ═══════════════════════════════════════════════════════════════════════════

I2C_BUS_ID = 1               # /dev/i2c-1 (100 kHz, fixé par le device tree)

# Politique d'erreur (LOGIQUE.md § 9) : I2C_RETRIES nouvelles tentatives sur
# OSError, puis défaut D6. Le délai est court parce qu'il bloque la boucle :
# 2 × 5 ms pendant un mouvement = 6 pas de retard de lecture capteur à 600 pas/s.
I2C_RETRIES = 2
I2C_RETRY_DELAY_S = 0.005

# Les registres de configuration de chaque MCP sont relus périodiquement : avec
# deux drivers de puissance qui commutent à proximité, un MCP peut perdre sa
# configuration et repasser ses sorties en entrée. Une relecture fausse →
# reconfiguration + avertissement ; deux de suite → défaut D7.
RELECTURE_CONFIG_MCP_PERIODE_S = 2.0

# ── Adresses des trois MCP23017 ────────────────────────────────────────────
MCP_RELAIS_ADDR = 0x24    # port A = 6 relais (A2..A7)        | port B = 6 boutons (B0..B5)
MCP_DRIVERS_ADDR = 0x25   # port A = DIR drivers 1..8 (A7..A0) | port B = ENA drivers 1..8 (B0..B7)
MCP_ENTREES_ADDR = 0x26   # port A = libre | port B = ACQUITTEMENT (B0) + 4 fins de course (B1..B4)

# ── Configuration attendue de chaque MCP : (port A, port B) ────────────────
# IODIR : bit à 1 = entrée, bit à 0 = sortie. Un port = une seule direction :
#         c'est ce qui autorise l'écriture d'octet atomique. NE PAS casser.
# GPPU  : pull-ups internes (~100 kΩ) sur toutes les entrées, comme en V1 et V4.
MCP_RELAIS_IODIR = (0x00, 0xFF)    # A sorties, B entrées
MCP_RELAIS_GPPU = (0x00, 0xFF)
MCP_DRIVERS_IODIR = (0x00, 0x00)   # A et B sorties
MCP_DRIVERS_GPPU = (0x00, 0x00)
MCP_ENTREES_IODIR = (0xFF, 0xFF)   # A et B entrées
MCP_ENTREES_GPPU = (0xFF, 0xFF)


# ═══════════════════════════════════════════════════════════════════════════
#  GPIO / lgpio  (Raspberry Pi 5, numérotation BCM)
# ═══════════════════════════════════════════════════════════════════════════

# Sur les noyaux récents, la puce RP1 est passée de gpiochip4 à gpiochip0. On
# essaie les candidats dans l'ordre et on ne retient que la puce dont le
# libellé contient GPIO_CHIP_LIBELLE : ouvrir la mauvaise puce ferait basculer
# la broche 17 d'un autre contrôleur.
GPIO_CHIP_CANDIDATS = (4, 0)
GPIO_CHIP_LIBELLE = "rp1"          # libellé attendu : « pinctrl-rp1 »

PUL_MERE = 17      # PUL driver 1 → axe mère   (confirmé PCB V4)
PUL_FILLE = 27     # PUL driver 2 → axe fille  (confirmé PCB V4)
BUZZER_GPIO = 26   # buzzer passif 5 V (confirmé PCB V4)

# Relais pilotés en GPIO direct, présents sur le PCB, NON utilisés. Le
# programme les réserve en sortie à 0 au démarrage : état connu, pas de broche
# flottante, disponibles pour plus tard.
GPIO_RELAIS_LIBRES = (16, 20)


# ═══════════════════════════════════════════════════════════════════════════
#  ÉLECTROVANNES  (sorties — MCP 0x24 port A)
# ═══════════════════════════════════════════════════════════════════════════
# 4 EV à 1 bobine, 1 relais chacune. Bit à 0 = bobine coupée = sortie AIR 1 =
# état sûr (débridé / lame haute). Bit à 1 = bobine alimentée = sortie AIR 2.
#
# ⚠ Les 6 relais du PCB sont câblés sur A2..A7 : A0 et A1 NE SORTENT NULLE PART
#   (V4 CLAUDE.md « LED1→A2 … LED6→A7 »). verifier_config() refuse A0/A1.
# ⚠ CORRESPONDANCE À CONFIRMER (test_4_relais.py).

EV_BRIDAGE_MERE = 2    # GPA2 — relais 1
EV_COUPE_MERE = 3      # GPA3 — relais 2
EV_BRIDAGE_FILLE = 4   # GPA4 — relais 3
EV_COUPE_FILLE = 5     # GPA5 — relais 4
# GPA6 (relais 5) et GPA7 (relais 6) : libres, maintenus à 0.


# ═══════════════════════════════════════════════════════════════════════════
#  BOUTONS  (entrées)
# ═══════════════════════════════════════════════════════════════════════════
# Correspondance relevée sur machine le 2026-10-08 (test_2_boutons.py).

# MCP 0x24 port B — 6 entrées câblées (B0..B5).
BTN_BRIDAGE_MERE = 0     # GPB0
BTN_COUPE_MERE = 2       # GPB2
BTN_POSITION_MERE = 1    # GPB1
BTN_BRIDAGE_FILLE = 5    # GPB5
BTN_COUPE_FILLE = 3      # GPB3
BTN_POSITION_FILLE = 4   # GPB4

# MCP 0x26 port B — 5 entrées câblées (B0..B4). Le 0x24 n'a pas de 7e entrée.
BTN_ACQUITTEMENT = 0     # GPB0

# True : bouton NO vers la masse + pull-up → appui = niveau bas.
# Confirmé par V1, V4 et old/test_7_boutons.py.
BOUTONS_ACTIFS_BAS = True

# Anti-rebond par temps de stabilité, non bloquant (méthode V1). Un appui n'est
# retenu qu'après ce temps de stabilité ; l'action part sur le front d'appui.
ANTI_REBOND_BOUTON_S = 0.05


# ═══════════════════════════════════════════════════════════════════════════
#  FINS DE COURSE  (entrées — MCP 0x26 port B)
# ═══════════════════════════════════════════════════════════════════════════
# Les 4 sur le MÊME port, volontairement : un seul octet lu, donc les quatre
# bits datent du même instant — le contrôle « deux capteurs actifs » (D2) porte
# sur une photo cohérente.
# ⚠ CORRESPONDANCE À CONFIRMER (test_3_capteurs.py).

# Correspondance et polarité relevées sur machine le 2026-10-08 (test_3_capteurs.py).
CAP_MERE_COUPE = 4          # GPB4
CAP_MERE_LIGATURAGE = 1     # GPB1
CAP_FILLE_COUPE = 2         # GPB2
CAP_FILLE_LIGATURAGE = 3    # GPB3

# Contact NO + pull-up : galet actionné = contact fermé = niveau BAS.
# Fil coupé ou connecteur débranché = niveau HAUT = « pas en position » :
# un capteur débranché ne peut jamais provoquer un faux arrêt, le moteur
# épuise son budget de pas et part en défaut D1.
# Polarité confirmée sur machine le 2026-10-08. ⚠ Reste à faire : le test de
# débranchement (test_3_capteurs.py, galet actionné, débrancher → voyant éteint).
CAPTEURS_ACTIFS_BAS = True

# Logique inverse des boutons : on ARRÊTE le moteur sur la lecture brute (pas
# d'attente de stabilité, qui coûterait des degrés), puis on CONFIRME l'arrivée
# par stabilité sur ANTI_REBOND_CAPTEUR_S.
ANTI_REBOND_CAPTEUR_S = 0.02

# Nombre de lectures brutes actives CONSÉCUTIVES pour arrêter le moteur. Filtre
# un parasite isolé (une seule lecture fausse) pour 4 ms de retard à 250 Hz,
# soit 0,6 pas à vitesse d'approche. 1 = arrêt sur la première lecture.
CAPTEUR_LECTURES_ARRET = 2

# Délai maximal entre la détection de la fin de course et sa confirmation
# (fin de surcourse + anti-rebond). Dépassé → défaut D5.
CONFIRMATION_CAPTEUR_MAX_S = 0.3

# À l'arrêt en position, la fin de course peut disparaître brièvement (choc de
# la coupe, vibration). Elle doit manquer PLUS de ce temps pour déclencher D5.
TOLERANCE_PERTE_CAPTEUR_S = 0.1          # ⚠ À AJUSTER si D5 intempestifs


# ═══════════════════════════════════════════════════════════════════════════
#  DRIVERS — DIR et ENA  (sorties — MCP 0x25)
# ═══════════════════════════════════════════════════════════════════════════
# Câblage du PCB Clean and Protech (V4 libs/io_board.py) :
#   DIR driver n → port A bit (8 − n)   ← INVERSÉ
#   ENA driver n → port B bit (n − 1)   ← direct

DIR_MERE = 7     # driver 1 → GPA7   ⚠ À CONFIRMER (test_5_moteur.py)
DIR_FILLE = 6    # driver 2 → GPA6   ⚠ À CONFIRMER (test_5_moteur.py)
ENA_MERE = 0     # driver 1 → GPB0
ENA_FILLE = 1    # driver 2 → GPB1

# ── Sémantique ENA sur le DM860H — PIÈGE ──────────────────────────────────
# Le signal ENA du DM860H DÉSACTIVE le moteur quand il est actif. Étage de
# sortie du PCB non inverseur (V4 config.py : ENA_ACTIVE_LEVEL = 0) :
ENA_MOTEUR_EXCITE = 0    # couple de maintien
ENA_MOTEUR_LIBRE = 1     # arbre libre
# Avant que Python ne tourne, les broches du MCP sont en entrée et la
# pull-down force 0 : les HUIT drivers sont excités dès la mise sous tension.
# Le programme écrit ENA = 1 sur les huit dès l'ouverture du bus.

# ── Sémantique DIR — PAR AXE ──────────────────────────────────────────────
# Les deux axes sont montés en miroir : le même niveau de DIR les fait tourner
# en sens opposés par rapport à leurs fins de course. Relevé sur machine le
# 2026-10-08 (test_5_moteur.py). Si un axe part du mauvais côté, inverser SA valeur.
DIR_VERS_LIGATURAGE = {POSTE_MERE: 0, POSTE_FILLE: 1}
DIR_VERS_COUPE = {poste: 1 - niveau for poste, niveau in DIR_VERS_LIGATURAGE.items()}

# Séquence avant chaque mouvement : ENA → pause → DIR → pause → impulsions.
# Ces deux pauses sont les seules attentes bloquantes de la boucle principale.
# Elles ne gênent pas : les deux axes ne bougent jamais en même temps.
MOTEUR_ENA_AVANT_DIR_S = 0.010    # laisse le rotor se caler après excitation
MOTEUR_DIR_AVANT_PAS_S = 0.005    # fiche : DIR stable avant le 1er front (mini 5 µs)

# False : ENA = 1 (moteur libre) dès l'arrivée en position. L'axe n'a pas
#         besoin de couple de maintien, et deux NEMA 34 excités dissipent une
#         vingtaine de watts dans le coffret.
# True  : moteur excité en position — si l'axe dérive sous l'effort de
#         ligaturage. En défaut et à l'arrêt, ENA = 1 dans tous les cas.
MOTEUR_MAINTIEN_EN_POSITION = False


# ═══════════════════════════════════════════════════════════════════════════
#  MOTEURS — GÉOMÉTRIE
# ═══════════════════════════════════════════════════════════════════════════

# DOIT correspondre aux interrupteurs SW5..SW8 des deux drivers (manuel
# JK-DM860H) : 1600 pas/tr = ON/OFF/ON/ON. Toute la géométrie en dépend : avec
# un écart, l'axe parcourt une autre course que celle calculée.
# 1600 plutôt que 3200 : la position vient des fins de course, pas du compte de
# pas, et à fréquence d'impulsions égale l'axe va deux fois plus vite.
DRIVER_PAS_PAR_TOUR = 1600

MOTEUR_REDUCTION = 1.0         # ⚠ À DÉTERMINER — rapport moteur → axe (> 1 si réducteur)
# Course COUPE ↔ LIGATURAGE de CHAQUE axe, en degrés d'axe. Relevé sur machine
# le 2026-10-08 (test_5_moteur.py : 197–199 pas pour la mère, 531–532 pour la
# fille, à 1600 pas/tr). ⚠ Les deux courses sont très différentes : à confirmer
# que c'est voulu mécaniquement.
# Affiné sur 726 trajets de rodage le 2026-10-08 : moyenne 205 pas (mère), 536 pas (fille).
MOTEUR_COURSE_DEGRES = {POSTE_MERE: 46.1, POSTE_FILLE: 120.6}

# Les nombres de pas sont CALCULÉS, jamais saisis : ajuster la course ou la
# réduction ne demande de toucher qu'une ligne.
PAS_PAR_DEGRE = DRIVER_PAS_PAR_TOUR * MOTEUR_REDUCTION / 360.0
MOTEUR_COURSE_PAS = {poste: round(PAS_PAR_DEGRE * degres)
                     for poste, degres in MOTEUR_COURSE_DEGRES.items()}


# ═══════════════════════════════════════════════════════════════════════════
#  MOTEURS — PROFIL DE MOUVEMENT  (LOGIQUE.md § 8)
# ═══════════════════════════════════════════════════════════════════════════
#
#  vitesse
#     │      ┌──────────┐
#  MAX│     ╱            ╲
#     │    ╱              ╲
#  APP│───╱                ╲──────────────────╳ ← fin de course (ou budget → D1)
#     └──────────────────────────────────────── pas
#       accél.   palier   décél.  approche lente
#                            │←── DISTANCE_APPROCHE ──→│ course nominale
#
# Le moteur démarre à la vitesse d'approche (un pas-à-pas ne démarre pas de 0),
# accélère, tient la vitesse max, décélère pour atteindre la vitesse d'approche
# MOTEUR_DISTANCE_APPROCHE_DEG avant la position nominale, puis avance lentement
# jusqu'à la fin de course. La phase lente n'a pas de longueur fixe : seul le
# budget de pas la borne.
#
# La vitesse réelle est légèrement INFÉRIEURE à la consigne (quelques %) : le
# thread compte chaque période depuis le pas réellement émis, un retard ralentit
# le moteur mais ne provoque jamais de rafale d'impulsions.

# ⚠ À AJUSTER SUR MACHINE — PAR AXE. Les deux axes n'ont ni la même course ni
# les mêmes frottements : chacun a sa vitesse et ses rampes.
# 2026-10-08 : accélérations ramenées de 3000 à 1500 pas/s² après un décrochage
# de la mère au 727e trajet de rodage (course courte, frottements).
MOTEUR_VITESSE_MAX_SPS = {POSTE_MERE: 600.0, POSTE_FILLE: 600.0}     # pas/s — palier
MOTEUR_ACCEL_SPS2 = {POSTE_MERE: 1500.0, POSTE_FILLE: 1500.0}        # pas/s² — rampe de montée
MOTEUR_DECEL_SPS2 = {POSTE_MERE: 1500.0, POSTE_FILLE: 1500.0}        # pas/s² — rampe de descente

# Commune aux deux axes : vitesse de démarrage, d'approche finale sur le galet,
# de recherche à l'initialisation.
MOTEUR_VITESSE_APPROCHE_SPS = 150.0     # pas/s

# True  : rampes « en S » — la vitesse suit une courbe douce (demi-cosinus),
#         sans cassure à l'entrée ni à la sortie de la rampe. Moins d'à-coups,
#         donc moins de vibrations. MOTEUR_ACCEL_SPS2 / DECEL sont alors
#         l'accélération de POINTE, atteinte au milieu de la rampe.
# False : rampes droites (accélération constante, cassures aux deux bouts).
MOTEUR_RAMPES_EN_S = True

MOTEUR_DISTANCE_APPROCHE_DEG = 5.0      # degrés d'axe parcourus à vitesse lente avant la position nominale
MOTEUR_MARGE_DEG = 10.0                 # degrés tolérés AU-DELÀ de la course nominale avant défaut D1
MOTEUR_SURCOURSE_DEG = 1.0              # degrés parcourus APRÈS la fin de course, pour s'asseoir franchement
                                        # sur le galet (0 = arrêt immédiat). Sans cela, le rotor qui se
                                        # recale à la coupure de ENA peut suffire à relâcher le galet.
MOTEUR_DEGAGEMENT_MAX_DEG = 20.0        # fin de course de départ encore active au-delà → défaut D4
                                        # (le moteur ne tourne pas). Doit couvrir : la marge (un axe arrêté
                                        # par un défaut D1 peut se trouver jusqu'à MOTEUR_MARGE_DEG au-delà
                                        # de sa fin de course, galet enfoncé), la surcourse, et le retard de
                                        # l'anti-rebond. verifier_config() le contrôle.

MOTEUR_LARGEUR_IMPULSION_US = 50        # µs — état haut de PUL. Fiche : mini 2,5 µs. Le driver
                                        # latche sur le front DESCENDANT (étage non inverseur).

# Calculés — ne pas modifier.
MOTEUR_APPROCHE_PAS = round(PAS_PAR_DEGRE * MOTEUR_DISTANCE_APPROCHE_DEG)
MOTEUR_MARGE_PAS = round(PAS_PAR_DEGRE * MOTEUR_MARGE_DEG)
MOTEUR_SURCOURSE_PAS = round(PAS_PAR_DEGRE * MOTEUR_SURCOURSE_DEG)
MOTEUR_DEGAGEMENT_MAX_PAS = round(PAS_PAR_DEGRE * MOTEUR_DEGAGEMENT_MAX_DEG)
# En S, la rampe est π/2 fois plus longue : c'est ce qui garde la même
# accélération de POINTE que la rampe droite.
_ALLONGEMENT_RAMPE = math.pi / 2 if MOTEUR_RAMPES_EN_S else 1.0


def _profil_axe(poste: str) -> tuple:
    """(fin de décélération, pas d'accélération, pas de décélération, vitesse de pointe).

    Sur une course trop courte pour atteindre MOTEUR_VITESSE_MAX_SPS, les deux
    rampes sont raccourcies dans la même proportion et la vitesse de pointe
    baisse d'autant : les accélérations restent celles demandées, l'axe ne
    fait simplement pas de palier.
    """
    pointe = MOTEUR_VITESSE_MAX_SPS[poste]
    ecart_carres = pointe ** 2 - MOTEUR_VITESSE_APPROCHE_SPS ** 2
    accel = math.ceil(ecart_carres / (2 * MOTEUR_ACCEL_SPS2[poste]) * _ALLONGEMENT_RAMPE)
    decel = math.ceil(ecart_carres / (2 * MOTEUR_DECEL_SPS2[poste]) * _ALLONGEMENT_RAMPE)
    fin_decel = MOTEUR_COURSE_PAS[poste] - MOTEUR_APPROCHE_PAS
    if 0 < fin_decel < accel + decel:
        part = fin_decel / (accel + decel)
        accel = int(accel * part)
        decel = fin_decel - accel
        pointe = math.sqrt(MOTEUR_VITESSE_APPROCHE_SPS ** 2 + ecart_carres * part)
    return fin_decel, accel, decel, pointe


# Par axe : poste → valeur.
_PROFILS = {poste: _profil_axe(poste) for poste in POSTES}
MOTEUR_FIN_DECEL_PAS = {poste: profil[0] for poste, profil in _PROFILS.items()}
MOTEUR_ACCEL_PAS = {poste: profil[1] for poste, profil in _PROFILS.items()}
MOTEUR_DECEL_PAS = {poste: profil[2] for poste, profil in _PROFILS.items()}
MOTEUR_VITESSE_POINTE_SPS = {poste: profil[3] for poste, profil in _PROFILS.items()}

# BUDGET DE PAS — borne DURE de chaque mouvement, référencement compris. Le
# thread d'impulsions s'arrête de lui-même au dernier pas autorisé. Il est
# compté depuis le relâchement du galet de départ (depuis le premier pas en
# recherche lente) : la cible peut donc être dépassée d'au plus MOTEUR_MARGE_DEG,
# où que l'axe ait démarré derrière son galet. Avant ce relâchement, c'est
# MOTEUR_DEGAGEMENT_MAX_DEG (défaut D4) qui borne le mouvement.
MOTEUR_BUDGET_PAS = {poste: pas + MOTEUR_MARGE_PAS for poste, pas in MOTEUR_COURSE_PAS.items()}


# ═══════════════════════════════════════════════════════════════════════════
#  MOTEURS — ORDRE ENTRE LES DEUX POSTES  (LOGIQUE.md § 5, I7 et I8)
# ═══════════════════════════════════════════════════════════════════════════
# ALLER (COUPE → LIGATURAGE) : le maître d'abord. L'appui POSITION de l'esclave
#   est REFUSÉ tant que le maître n'est pas arrivé en ligaturage depuis au
#   moins RETARD_SENS_ALLER_S. Rien n'est mémorisé.
# RETOUR (LIGATURAGE → COUPE) : l'esclave d'abord. L'appui POSITION du maître
#   est REFUSÉ tant que l'esclave n'est pas revenu en position coupe.
# INITIALISATION : l'esclave est référencé en premier, puis le maître.

MOTEUR_MAITRE = POSTE_MERE     # ⚠ À DÉTERMINER SUR MACHINE — POSTE_MERE ou POSTE_FILLE
RETARD_SENS_ALLER_S = 0.5      # ⚠ À AJUSTER — s, délai APRÈS l'arrivée du maître avant d'accepter l'esclave


# ═══════════════════════════════════════════════════════════════════════════
#  TEMPORISATIONS DES ACTIONS  (secondes)
# ═══════════════════════════════════════════════════════════════════════════
# Règle universelle (LOGIQUE.md § 2.2) : toute action a une durée. Pendant
# cette durée le poste est occupé et ses trois boutons sont refusés. L'état de
# l'actionneur ne change qu'à la FIN de l'action : la variable ne peut jamais
# être en avance sur le vérin.

# Séquence de coupe : attente → impulsion EV → attente → fin (double bip).
TEMPS_AVANT_COUPE_S = 0.2      # ⚠ À AJUSTER — laisse l'opérateur dégager la main après l'appui
TEMPS_COUPE_S = 0.75           # ⚠ À AJUSTER — EV coupe alimentée (valeur V1, dernier réglage)
TEMPS_APRES_COUPE_S = 0.5      # ⚠ À AJUSTER — garantit la lame remontée avant tout nouvel appui

# Bridage : l'EV bascule immédiatement, l'état « bridé / débridé » n'est retenu
# qu'après ce temps. Doit couvrir la course complète du vérin.
TEMPS_MANOEUVRE_BRIDAGE_S = 0.5   # ⚠ À AJUSTER — chronométrer la course du vérin (test_4)

# Après CHAQUE action (bridage, coupe, mise en position), les boutons du poste
# restent refusés ce temps-là. Protège contre le double appui.
TEMPS_GARDE_APRES_ACTION_S = 0.3


# ═══════════════════════════════════════════════════════════════════════════
#  BOUCLE PRINCIPALE
# ═══════════════════════════════════════════════════════════════════════════
# 250 Hz : latence de décision 4 ms, soit ~2,4 pas à 600 pas/s et 0,6 pas à
# vitesse d'approche. Coût I2C ≈ 600 transactions/s, ~25 % du bus.

FREQUENCE_BOUCLE_HZ = 250
PERIODE_BOUCLE_S = 1.0 / FREQUENCE_BOUCLE_HZ

# Intervalle de bascule du GIL entre threads Python (défaut 5 ms). Réduit pour
# que le thread d'impulsions récupère la main vite quand son pas arrive à
# échéance, même si la boucle principale est en train de calculer.
PYTHON_SWITCH_INTERVAL_S = 0.0005

# Attente maximale de la fin d'un thread d'impulsions après un ordre d'arrêt
# (défaut, arrêt programme). Un thread s'arrête en moins d'une période de pas.
ARRET_THREAD_MAX_S = 0.2


# ═══════════════════════════════════════════════════════════════════════════
#  BUZZER  (GPIO 26, PWM lgpio)
# ═══════════════════════════════════════════════════════════════════════════
# Non bloquant. Une panne de buzzer ne bloque jamais la machine : il se
# désactive et le journal le signale.
#   appui accepté ........... 1 bip court
#   fin d'action ............ 2 bips courts (coupe, bridage, mise en position)
#   machine prête ........... 2 bips courts
#   appui refusé ............ 1 bip LONG — distinct du double bip de fin d'action
#   entrée en défaut ........ 1 bip très long

BUZZER_ACTIF = True
BUZZER_FREQ_HZ = 2000           # résonance nominale du buzzer passif
BUZZER_PUISSANCE_PCT = 50       # rapport cyclique PWM, 0..100
BIP_COURT_S = 0.08
BIP_PAUSE_S = 0.08
BIP_REFUS_S = 0.3
BIP_DEFAUT_S = 0.8
BUZZER_FILE_MAX_SEGMENTS = 12   # au-delà, les bips demandés sont ignorés (boutons martelés)


# ═══════════════════════════════════════════════════════════════════════════
#  JOURNAL ET COMPTEURS  (dans le dossier du programme)
# ═══════════════════════════════════════════════════════════════════════════

_RACINE = Path(__file__).resolve().parent

CHEMIN_JOURNAL = _RACINE / "logs" / "vitis_optima.log"
JOURNAL_TAILLE_MAX_OCTETS = 1_000_000   # rotation à 1 Mo
JOURNAL_NB_ARCHIVES = 5                 # vitis_optima.log.1 … .5

# Un compteur par bouton (acceptés / refusés) et par actionneur, pas de global.
# Écriture atomique (fichier temporaire + os.replace). Jamais pendant un
# mouvement : une écriture sur carte SD peut bloquer la boucle 100 ms.
CHEMIN_COMPTEURS = _RACINE / "etat" / "compteurs.json"
COMPTEURS_PERIODE_ECRITURE_S = 30.0


# ═══════════════════════════════════════════════════════════════════════════
#  DRIVERS JK-DM860H — RÉGLAGES PHYSIQUES  (documentation, aucune dépendance code)
# ═══════════════════════════════════════════════════════════════════════════
# Réglage des DEUX drivers, SW1 → SW8 (1 = ON), d'après le manuel JK-DM860H :
#   SW1=ON  SW2=ON  SW3=OFF        → 4,28 A RMS / 5,14 A crête
#   SW4=OFF                        → demi-courant à l'arrêt
#   SW5=ON  SW6=OFF SW7=ON SW8=ON  → 1600 impulsions/tour (= DRIVER_PAS_PAR_TOUR)
DRIVER_DIP_SWITCH = "11001011"

# ⚠ À CONFIRMER : courant nominal sur la plaque du moteur (noté 6,0 A / phase).
#   Crans SW1/SW2/SW3 du manuel :
#     OFF/OFF/ON  → 3,71 A RMS / 4,45 A crête  (si ça chauffe et que le couple suffit)
#     ON/ON/OFF   → 4,28 A RMS / 5,14 A crête  (valeur actuelle, ~70 % de 6 A)
#     OFF/ON/OFF  → 4,86 A RMS / 5,83 A crête  (si l'axe décroche)
#     OFF/OFF/OFF → 6,00 A RMS / 7,20 A crête  (maximum, moteur de 6 A seulement)
DRIVER_COURANT_CRETE_A = 5.14

# Ce driver n'a PAS de sortie d'alarme : une panne n'est signalée que par sa
# LED rouge. Les seuls détecteurs logiciels sont D4 (le moteur ne quitte pas sa
# fin de course de départ) et D1 (budget de pas épuisé).


# ═══════════════════════════════════════════════════════════════════════════
#  VÉRIFICATION DE LA CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

def verifier_config() -> None:
    """Détecte les erreurs de saisie de ce fichier AVANT tout accès matériel.

    Lève ValueError avec la liste complète des erreurs.
    """
    erreurs: list[str] = []

    def _dans(nom: str, valeur, permis) -> None:
        if valeur not in permis:
            erreurs.append(f"{nom} = {valeur!r} — attendu parmi {sorted(permis)}")

    def _positif(nom: str, valeur) -> None:
        if not valeur > 0:
            erreurs.append(f"{nom} = {valeur} — doit être strictement positif")

    def _distincts(libelle: str, groupe: dict) -> None:
        if len(set(groupe.values())) != len(groupe):
            erreurs.append(f"{libelle} : deux fonctions sur le même bit — "
                           + ", ".join(f"{n}={b}" for n, b in groupe.items()))

    # ── Bits : uniquement ceux qui sont réellement câblés sur le PCB
    ev = {"EV_BRIDAGE_MERE": EV_BRIDAGE_MERE, "EV_COUPE_MERE": EV_COUPE_MERE,
          "EV_BRIDAGE_FILLE": EV_BRIDAGE_FILLE, "EV_COUPE_FILLE": EV_COUPE_FILLE}
    for nom, bit in ev.items():
        _dans(nom, bit, set(range(2, 8)))          # relais sur A2..A7 seulement
    _distincts("EV (0x24 A)", ev)

    btn = {"BTN_BRIDAGE_MERE": BTN_BRIDAGE_MERE, "BTN_COUPE_MERE": BTN_COUPE_MERE,
           "BTN_POSITION_MERE": BTN_POSITION_MERE, "BTN_BRIDAGE_FILLE": BTN_BRIDAGE_FILLE,
           "BTN_COUPE_FILLE": BTN_COUPE_FILLE, "BTN_POSITION_FILLE": BTN_POSITION_FILLE}
    for nom, bit in btn.items():
        _dans(nom, bit, set(range(0, 6)))          # entrées câblées B0..B5
    _distincts("boutons (0x24 B)", btn)
    _dans("BTN_ACQUITTEMENT", BTN_ACQUITTEMENT, set(range(0, 5)))   # 0x26 B0..B4

    cap = {"CAP_MERE_COUPE": CAP_MERE_COUPE, "CAP_MERE_LIGATURAGE": CAP_MERE_LIGATURAGE,
           "CAP_FILLE_COUPE": CAP_FILLE_COUPE, "CAP_FILLE_LIGATURAGE": CAP_FILLE_LIGATURAGE}
    for nom, bit in cap.items():
        _dans(nom, bit, set(range(0, 5)))          # entrées câblées B0..B4
    # Même port que ACQUITTEMENT : aucun bit en double entre les cinq.
    _distincts("fins de course + acquittement (0x26 B)", {**cap, "BTN_ACQUITTEMENT": BTN_ACQUITTEMENT})

    for nom, bit in (("DIR_MERE", DIR_MERE), ("DIR_FILLE", DIR_FILLE),
                     ("ENA_MERE", ENA_MERE), ("ENA_FILLE", ENA_FILLE)):
        _dans(nom, bit, set(range(0, 8)))
    _distincts("DIR (0x25 A)", {"DIR_MERE": DIR_MERE, "DIR_FILLE": DIR_FILLE})
    _distincts("ENA (0x25 B)", {"ENA_MERE": ENA_MERE, "ENA_FILLE": ENA_FILLE})

    # ── Niveaux logiques
    for nom, val in (("ENA_MOTEUR_EXCITE", ENA_MOTEUR_EXCITE), ("ENA_MOTEUR_LIBRE", ENA_MOTEUR_LIBRE)):
        _dans(nom, val, {0, 1})
    if ENA_MOTEUR_EXCITE == ENA_MOTEUR_LIBRE:
        erreurs.append("ENA_MOTEUR_EXCITE et ENA_MOTEUR_LIBRE identiques")
    for nom, table in (("DIR_VERS_LIGATURAGE", DIR_VERS_LIGATURAGE),
                       ("MOTEUR_COURSE_DEGRES", MOTEUR_COURSE_DEGRES),
                       ("MOTEUR_VITESSE_MAX_SPS", MOTEUR_VITESSE_MAX_SPS),
                       ("MOTEUR_ACCEL_SPS2", MOTEUR_ACCEL_SPS2),
                       ("MOTEUR_DECEL_SPS2", MOTEUR_DECEL_SPS2)):
        if set(table) != set(POSTES):
            erreurs.append(f"{nom} : une valeur par poste attendue ({POSTES}), trouvé {sorted(table)}")
    for poste, niveau in DIR_VERS_LIGATURAGE.items():
        _dans(f"DIR_VERS_LIGATURAGE[{poste}]", niveau, {0, 1})

    # ── GPIO : aucune broche en double
    gpio = [PUL_MERE, PUL_FILLE, BUZZER_GPIO, *GPIO_RELAIS_LIBRES]
    if len(set(gpio)) != len(gpio):
        erreurs.append(f"GPIO en double parmi PUL / buzzer / relais libres : {gpio}")

    # ── Adresses MCP distinctes
    if len({MCP_RELAIS_ADDR, MCP_DRIVERS_ADDR, MCP_ENTREES_ADDR}) != 3:
        erreurs.append("MCP_RELAIS_ADDR / MCP_DRIVERS_ADDR / MCP_ENTREES_ADDR : trois adresses distinctes attendues")

    # ── Poste maître
    _dans("MOTEUR_MAITRE", MOTEUR_MAITRE, set(POSTES))

    # ── Durées et grandeurs strictement positives
    for nom, val in (
        ("I2C_RETRY_DELAY_S", I2C_RETRY_DELAY_S),
        ("RELECTURE_CONFIG_MCP_PERIODE_S", RELECTURE_CONFIG_MCP_PERIODE_S),
        ("ANTI_REBOND_BOUTON_S", ANTI_REBOND_BOUTON_S),
        ("ANTI_REBOND_CAPTEUR_S", ANTI_REBOND_CAPTEUR_S),
        ("CAPTEUR_LECTURES_ARRET", CAPTEUR_LECTURES_ARRET),
        ("CONFIRMATION_CAPTEUR_MAX_S", CONFIRMATION_CAPTEUR_MAX_S),
        ("TOLERANCE_PERTE_CAPTEUR_S", TOLERANCE_PERTE_CAPTEUR_S),
        ("DRIVER_PAS_PAR_TOUR", DRIVER_PAS_PAR_TOUR),
        ("MOTEUR_REDUCTION", MOTEUR_REDUCTION),
        *((f"MOTEUR_COURSE_DEGRES[{poste}]", degres) for poste, degres in MOTEUR_COURSE_DEGRES.items()),
        *((f"MOTEUR_VITESSE_MAX_SPS[{poste}]", v) for poste, v in MOTEUR_VITESSE_MAX_SPS.items()),
        ("MOTEUR_VITESSE_APPROCHE_SPS", MOTEUR_VITESSE_APPROCHE_SPS),
        *((f"MOTEUR_ACCEL_SPS2[{poste}]", v) for poste, v in MOTEUR_ACCEL_SPS2.items()),
        *((f"MOTEUR_DECEL_SPS2[{poste}]", v) for poste, v in MOTEUR_DECEL_SPS2.items()),
        ("MOTEUR_DISTANCE_APPROCHE_DEG", MOTEUR_DISTANCE_APPROCHE_DEG),
        ("MOTEUR_MARGE_DEG", MOTEUR_MARGE_DEG),
        ("MOTEUR_DEGAGEMENT_MAX_DEG", MOTEUR_DEGAGEMENT_MAX_DEG),
        ("MOTEUR_LARGEUR_IMPULSION_US", MOTEUR_LARGEUR_IMPULSION_US),
        ("TEMPS_COUPE_S", TEMPS_COUPE_S),
        ("TEMPS_MANOEUVRE_BRIDAGE_S", TEMPS_MANOEUVRE_BRIDAGE_S),
        ("FREQUENCE_BOUCLE_HZ", FREQUENCE_BOUCLE_HZ),
        ("PYTHON_SWITCH_INTERVAL_S", PYTHON_SWITCH_INTERVAL_S),
        ("ARRET_THREAD_MAX_S", ARRET_THREAD_MAX_S),
        ("COMPTEURS_PERIODE_ECRITURE_S", COMPTEURS_PERIODE_ECRITURE_S),
    ):
        _positif(nom, val)

    for nom, val in (("RETARD_SENS_ALLER_S", RETARD_SENS_ALLER_S),
                     ("TEMPS_AVANT_COUPE_S", TEMPS_AVANT_COUPE_S),
                     ("TEMPS_APRES_COUPE_S", TEMPS_APRES_COUPE_S),
                     ("TEMPS_GARDE_APRES_ACTION_S", TEMPS_GARDE_APRES_ACTION_S),
                     ("MOTEUR_SURCOURSE_DEG", MOTEUR_SURCOURSE_DEG),
                     ("I2C_RETRIES", I2C_RETRIES)):
        if val < 0:
            erreurs.append(f"{nom} = {val} — doit être positif ou nul")

    if not 50 <= FREQUENCE_BOUCLE_HZ <= 1000:
        erreurs.append(f"FREQUENCE_BOUCLE_HZ = {FREQUENCE_BOUCLE_HZ} — attendu entre 50 et 1000")

    # ── Cohérence du profil de mouvement
    vitesse_max = max(MOTEUR_VITESSE_MAX_SPS.values())
    for poste, vitesse in MOTEUR_VITESSE_MAX_SPS.items():
        if MOTEUR_VITESSE_APPROCHE_SPS > vitesse:
            erreurs.append(f"MOTEUR_VITESSE_APPROCHE_SPS > MOTEUR_VITESSE_MAX_SPS[{poste}]")
    if MOTEUR_LARGEUR_IMPULSION_US * 1e-6 >= 0.5 / vitesse_max:
        erreurs.append("MOTEUR_LARGEUR_IMPULSION_US trop grand pour MOTEUR_VITESSE_MAX_SPS")
    for poste in POSTES:
        # Une course trop courte pour atteindre la vitesse max n'est pas une
        # erreur : _profil_axe() raccourcit les rampes et baisse la pointe.
        if MOTEUR_FIN_DECEL_PAS.get(poste, 1) <= 0:
            erreurs.append(f"{poste} : MOTEUR_DISTANCE_APPROCHE_DEG >= course de l'axe")
        if MOTEUR_DEGAGEMENT_MAX_PAS >= MOTEUR_COURSE_PAS.get(poste, MOTEUR_DEGAGEMENT_MAX_PAS + 1):
            erreurs.append(f"{poste} : MOTEUR_DEGAGEMENT_MAX_DEG >= course de l'axe")
    if MOTEUR_SURCOURSE_PAS >= MOTEUR_MARGE_PAS:
        erreurs.append("MOTEUR_SURCOURSE_DEG >= MOTEUR_MARGE_DEG — la surcourse doit tenir dans la marge")
    # D4 ne doit pas se déclencher à tort quand l'axe part de loin derrière son
    # galet (après un D1) : marge + surcourse + pas parcourus pendant le retard
    # de l'anti-rebond à vitesse max.
    retard_pas = vitesse_max * (ANTI_REBOND_CAPTEUR_S + 2 * PERIODE_BOUCLE_S)
    degagement_mini = MOTEUR_MARGE_PAS + MOTEUR_SURCOURSE_PAS + retard_pas
    if MOTEUR_DEGAGEMENT_MAX_PAS <= degagement_mini:
        erreurs.append(
            f"MOTEUR_DEGAGEMENT_MAX_DEG trop petit : {MOTEUR_DEGAGEMENT_MAX_PAS} pas, il en faut plus de "
            f"{degagement_mini:.0f} (marge + surcourse + retard d'anti-rebond)")

    # ── Confirmation d'arrivée : surcourse à vitesse d'approche + anti-rebond
    #    + lectures d'arrêt doivent tenir dans CONFIRMATION_CAPTEUR_MAX_S.
    duree_confirmation = (MOTEUR_SURCOURSE_PAS / MOTEUR_VITESSE_APPROCHE_SPS
                          + ANTI_REBOND_CAPTEUR_S + 3 * PERIODE_BOUCLE_S)
    if duree_confirmation >= CONFIRMATION_CAPTEUR_MAX_S:
        erreurs.append(
            f"CONFIRMATION_CAPTEUR_MAX_S = {CONFIRMATION_CAPTEUR_MAX_S} s — trop court : la surcourse "
            f"et l'anti-rebond demandent déjà {duree_confirmation:.3f} s")

    if erreurs:
        raise ValueError("config.py :\n  - " + "\n  - ".join(erreurs))
