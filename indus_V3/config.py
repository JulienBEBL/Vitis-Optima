# -*- coding: utf-8 -*-
"""
config.py — Configuration matérielle et temporisations de la Vitis Optima indus V3.

C'EST LE SEUL FICHIER À MODIFIER pour adapter le programme au câblage réel.
Aucun numéro de broche, aucune durée, aucune adresse ne doit apparaître ailleurs
dans le code. Tout le reste importe ce module (`import config as cfg`).

La logique de pilotage est décrite dans LOGIQUE.md (version 3.1).
Les écarts avec la V2 et le pourquoi sont dans CHANGEMENTS_V3.md.
La mise en service et les tests sont décrits dans README.md.

═══════════════════════════════════════════════════════════════════════════════
 MACHINE
═══════════════════════════════════════════════════════════════════════════════
Deux postes « mère » et « fille », TOTALEMENT INDÉPENDANTS. Chacun possède :
  - 1 EV de MANDRIN, 1 bobine : bobine coupée = MANDRIN OUVERT (le mandrin
    pneumatique serre la branche : c'est le bridage)
  - 1 EV de COUPE,   1 bobine : bobine coupée = LAME HAUTE
  - 1 moteur NEMA 24 (StepperOnline 24IP65-30) + driver JK-DM860H qui fait
    TOURNER le mandrin entre deux butées : HORAIRE et ANTIHORAIRE (≈ 130°)
  - 4 boutons : BRIDAGE, ROTATION +, ROTATION −, COUPE
Plus 1 bouton ACQUITTEMENT commun et 1 buzzer. Aucun voyant.
Le bloc moteur se déplace à la main sur un guide de translation : aucun capteur.

⚠ Le mandrin n'a PAS de joint tournant pneumatique : son tuyau suit la
  rotation. Sortir de la plage l'arracherait. Voir MARGE_DEPASSEMENT_DEG.

Bit relais à 0 = bobine coupée = état sûr (mandrin ouvert, lame haute). Toute
sortie du programme, et tout défaut d'un poste, remet ses relais à 0.

L'arrêt d'urgence est câblé en dur et coupe tout, Raspberry Pi comprise.
Le logiciel ne le voit pas : au réarmement, le programme repart de zéro.

PCB : « indus V1 » de Clean and Protech, 8 emplacements de drivers.
Seuls les drivers 1 (poste mère) et 2 (poste fille) sont utilisés.

═══════════════════════════════════════════════════════════════════════════════
 VALEURS NON CONFIRMÉES — à vérifier avec les scripts de tests/ (voir README.md)
═══════════════════════════════════════════════════════════════════════════════
  ⚠ À ATTRIBUER   EV_* ................. relais ↔ EV                     (test_4)
                  CAP_* ................ butée ↔ bit, sens               (test_3)
                  DIR_VERS_HORAIRE ..... sens de rotation par poste      (test_5)
                  SENS_ROTATION_PLUS ... sens du bouton ROTATION +       (test_5)
  ⚠ À CONFIRMER   DIP des drivers (6400 pas/tr, 4,28 A RMS) — LIRE L'ÉTIQUETTE
  ⚠ À MESURER     PLAGE_NOMINALE_DEG (test_5), MARGE_DEPASSEMENT_DEG (tuyau)
  ⚠ À AJUSTER     vitesses et rampe de rotation, vitesses d'initialisation,
                  temporisations pneumatiques
"""

from __future__ import annotations

from pathlib import Path


# ═══════════════════════════════════════════════════════════════════════════
#  VOCABULAIRE MÉTIER  (chaînes canoniques — définies ici pour éviter la dérive)
# ═══════════════════════════════════════════════════════════════════════════

POSTE_MERE = "mere"
POSTE_FILLE = "fille"
POSTES = (POSTE_MERE, POSTE_FILLE)

# Sens de rotation du mandrin, vus depuis le même côté pour les deux postes
# (⚠ convention à fixer à la mise en service et à garder : le côté opérateur).
SENS_HORAIRE = "horaire"
SENS_ANTIHORAIRE = "antihoraire"
SENS = (SENS_HORAIRE, SENS_ANTIHORAIRE)


def sens_oppose(sens: str) -> str:
    return SENS_ANTIHORAIRE if sens == SENS_HORAIRE else SENS_HORAIRE


# ═══════════════════════════════════════════════════════════════════════════
#  BUS I2C  (inchangé depuis la V2)
# ═══════════════════════════════════════════════════════════════════════════

I2C_BUS_ID = 1               # /dev/i2c-1 (100 kHz, fixé par le device tree)

# Politique d'erreur (LOGIQUE.md § 9) : I2C_RETRIES nouvelles tentatives sur
# OSError, puis défaut D6 (les DEUX postes : le bus est commun). Le délai est
# court parce qu'il bloque la boucle.
I2C_RETRIES = 2
I2C_RETRY_DELAY_S = 0.005

# Les registres de configuration de chaque MCP sont relus périodiquement : avec
# deux drivers de puissance qui commutent à proximité, un MCP peut perdre sa
# configuration et repasser ses sorties en entrée. Une relecture fausse →
# reconfiguration + avertissement ; deux de suite → défaut D7 (les deux postes).
RELECTURE_CONFIG_MCP_PERIODE_S = 2.0

# ── Adresses des trois MCP23017 ────────────────────────────────────────────
MCP_RELAIS_ADDR = 0x24    # port A = 6 relais (A2..A7)        | port B = 6 boutons (B0..B5)
MCP_DRIVERS_ADDR = 0x25   # port A = DIR drivers 1..8 (A7..A0) | port B = ENA drivers 1..8 (B0..B7)
MCP_ENTREES_ADDR = 0x26   # port A = 3 boutons (A5..A7)       | port B = 4 butées (B1..B4)

# ── Configuration attendue de chaque MCP : (port A, port B) ────────────────
# IODIR : bit à 1 = entrée, bit à 0 = sortie. Un port = une seule direction :
#         c'est ce qui autorise l'écriture d'octet atomique. NE PAS casser.
# GPPU  : pull-ups internes (~100 kΩ) sur toutes les entrées.
MCP_RELAIS_IODIR = (0x00, 0xFF)    # A sorties, B entrées
MCP_RELAIS_GPPU = (0x00, 0xFF)
MCP_DRIVERS_IODIR = (0x00, 0x00)   # A et B sorties
MCP_DRIVERS_GPPU = (0x00, 0x00)
MCP_ENTREES_IODIR = (0xFF, 0xFF)   # A et B entrées — le port A porte les 2 nouveaux boutons
MCP_ENTREES_GPPU = (0xFF, 0xFF)


# ═══════════════════════════════════════════════════════════════════════════
#  GPIO / lgpio  (Raspberry Pi 5, numérotation BCM — inchangé depuis la V2)
# ═══════════════════════════════════════════════════════════════════════════

# Sur les noyaux récents, la puce RP1 est passée de gpiochip4 à gpiochip0. On
# essaie les candidats dans l'ordre et on ne retient que la puce dont le
# libellé contient GPIO_CHIP_LIBELLE : ouvrir la mauvaise puce ferait basculer
# la broche 17 d'un autre contrôleur.
GPIO_CHIP_CANDIDATS = (4, 0)
GPIO_CHIP_LIBELLE = "rp1"          # libellé attendu : « pinctrl-rp1 »

# Greffon (fille) branché sur le DRIVER 1 du PCB, relevé le 2026-10-28 (test_5).
# Mère : driver 2, provisoire (moteur mère pas encore monté).
PUL_FILLE = 17     # PUL driver 1 → moteur fille  (relevé le 2026-10-28)
PUL_MERE = 27      # PUL driver 2 → moteur mère   (⚠ provisoire)
BUZZER_GPIO = 26   # buzzer passif 5 V (confirmé PCB V4)

# Relais pilotés en GPIO direct, présents sur le PCB, NON utilisés. Le
# programme les réserve en sortie à 0 au démarrage : état connu, pas de broche
# flottante, disponibles pour plus tard.
GPIO_RELAIS_LIBRES = (16, 20)


# ═══════════════════════════════════════════════════════════════════════════
#  ÉLECTROVANNES  (sorties — MCP 0x24 port A)
# ═══════════════════════════════════════════════════════════════════════════
# 4 EV à 1 bobine, 1 relais chacune, sur les 4 mêmes relais qu'en V2.
#   bit à 0 = bobine coupée     = MANDRIN OUVERT / LAME HAUTE  (état sûr)
#   bit à 1 = bobine alimentée  = MANDRIN FERMÉ  / LAME BASSE
#
# ⚠ Les 6 relais du PCB sont câblés sur A2..A7 : A0 et A1 NE SORTENT NULLE PART
#   (V4 CLAUDE.md « LED1→A2 … LED6→A7 »). verifier_config() refuse A0/A1.
# ⚠ ATTRIBUTION À REFAIRE (test_4_relais.py). Valeurs de départ = relevé V2 du
#   2026-10-13, l'ancien bridage devenant le mandrin.

EV_COUPE_FILLE = 2       # GPA2 — relais 1   ⚠ à attribuer
EV_COUPE_MERE = 3        # GPA3 — relais 2   ⚠ à attribuer
EV_MANDRIN_MERE = 4      # GPA4 — relais 3   ⚠ à attribuer
EV_MANDRIN_FILLE = 5     # GPA5 — relais 4   ⚠ à attribuer
# GPA6 (relais 5) et GPA7 (relais 6) : libres, maintenus à 0.


# ═══════════════════════════════════════════════════════════════════════════
#  BOUTONS  (entrées)
# ═══════════════════════════════════════════════════════════════════════════
# 4 boutons par poste + ACQUITTEMENT = 9 entrées. Chaque bouton est désigné par
# (MCP, port, bit) : le câblage V3 répartit les boutons sur trois ports.
# Entrées câblées sur le PCB : 0x24 port B bits 0..5, 0x26 port A bits 4..7,
# 0x26 port B bits 0..4 (partagé avec les butées). verifier_config() le contrôle.
# Le 0x26 est lu en une seule transaction (ports A et B) : un bouton sur le
# port A ne coûte aucune lecture I2C de plus.
#
# Relevé sur machine le 2026-10-28 (test_2_boutons.py, attribution guidée) :
# 9 contacts NO, repos à 1.
BTN_BRIDAGE_MERE = ("0x24", "B", 5)          # GPB5
BTN_ROTATION_PLUS_MERE = ("0x24", "B", 4)    # GPB4
BTN_ROTATION_MOINS_MERE = ("0x24", "B", 3)   # GPB3
BTN_COUPE_MERE = ("0x26", "A", 5)            # GPA5
BTN_BRIDAGE_FILLE = ("0x24", "B", 1)         # GPB1
BTN_ROTATION_PLUS_FILLE = ("0x24", "B", 0)   # GPB0
BTN_ROTATION_MOINS_FILLE = ("0x26", "A", 7)  # GPA7
BTN_COUPE_FILLE = ("0x24", "B", 2)           # GPB2
BTN_ACQUITTEMENT = ("0x26", "A", 6)          # GPA6
# Libres : 0x26 GPA4, 0x26 GPB0 (ancien ACQUITTEMENT de la V2).

# Entrées câblées sur le PCB, par port. Ne pas modifier.
ENTREES_BOUTONS_CABLEES = {("0x24", "B"): range(0, 6), ("0x26", "A"): range(4, 8),
                           ("0x26", "B"): range(0, 5)}

# True : bouton NO vers la masse + pull-up → appui = niveau bas.
# Confirmé sur machine le 2026-10-28 : les 9 boutons au repos à 1 (contacts NO).
BOUTONS_ACTIFS_BAS = True

# Anti-rebond par temps de stabilité, non bloquant. Un appui n'est retenu
# qu'après ce temps de stabilité ; l'action part sur le front d'appui.
# ⚠ Exception : le RELÂCHEMENT d'un bouton de rotation est pris sur la lecture
#   BRUTE, sans anti-rebond — à 10°/s, 50 ms d'attente feraient 0,5° de trop.
ANTI_REBOND_BOUTON_S = 0.05


# ═══════════════════════════════════════════════════════════════════════════
#  BUTÉES DE ROTATION  (fins de course — entrées MCP 0x26 port B)
# ═══════════════════════════════════════════════════════════════════════════
# Les 4 sur le MÊME port, volontairement : un seul octet lu, donc les quatre
# bits datent du même instant — le contrôle « deux butées actives » (D2) porte
# sur une photo cohérente.
# Greffon (fille) : relevé sur machine le 2026-10-28 (test_3, attribution), contacts NO.
# Mère : butées pas encore branchées — bits restants, PROVISOIRES.

CAP_FILLE_HORAIRE = 1        # GPB1   relevé le 2026-10-28
CAP_FILLE_ANTIHORAIRE = 4    # GPB4   relevé le 2026-10-28
CAP_MERE_HORAIRE = 2         # GPB2   ⚠ provisoire, à attribuer au branchement (test_3)
CAP_MERE_ANTIHORAIRE = 3     # GPB3   ⚠ provisoire, à attribuer au branchement (test_3)

# Contact NO + pull-up : galet actionné = contact fermé = niveau BAS.
# Fil coupé ou connecteur débranché = niveau HAUT = « pas en butée » :
# un capteur débranché ne provoque jamais de faux arrêt, le moteur épuise son
# budget de pas et part en défaut D1 (ou D8 à l'initialisation).
CAPTEURS_ACTIFS_BAS = True

# On ARRÊTE le moteur sur la lecture brute (pas d'attente de stabilité), puis
# on CONFIRME l'arrivée par stabilité sur ANTI_REBOND_CAPTEUR_S.
ANTI_REBOND_CAPTEUR_S = 0.02

# Nombre de lectures brutes actives CONSÉCUTIVES pour arrêter le moteur. Filtre
# un parasite isolé pour 4 ms de retard à 250 Hz (0,04° à 10°/s).
CAPTEUR_LECTURES_ARRET = 2

# Délai maximal entre la détection de la butée et sa confirmation par
# l'anti-rebond. Dépassé → défaut D5.
CONFIRMATION_CAPTEUR_MAX_S = 0.3

# À l'arrêt, une butée peut battre brièvement (choc de la coupe, vibration).
# Elle doit changer d'état PLUS de ce temps pour déclencher D5.
TOLERANCE_PERTE_CAPTEUR_S = 0.1          # ⚠ À AJUSTER si D5 intempestifs


# ═══════════════════════════════════════════════════════════════════════════
#  DRIVERS — DIR et ENA  (sorties — MCP 0x25)
# ═══════════════════════════════════════════════════════════════════════════
# Câblage du PCB Clean and Protech (V4 libs/io_board.py), inchangé :
#   DIR driver n → port A bit (8 − n)   ← INVERSÉ
#   ENA driver n → port B bit (n − 1)   ← direct

DIR_FILLE = 7    # driver 1 → GPA7   (relevé le 2026-10-28)
ENA_FILLE = 0    # driver 1 → GPB0
DIR_MERE = 6     # driver 2 → GPA6   (⚠ provisoire, moteur mère pas encore monté)
ENA_MERE = 1     # driver 2 → GPB1

# ── Sémantique ENA sur le DM860H — PIÈGE ──────────────────────────────────
# Le signal ENA du DM860H DÉSACTIVE le moteur quand il est actif. Étage de
# sortie du PCB non inverseur :
ENA_MOTEUR_EXCITE = 0    # couple de maintien
ENA_MOTEUR_LIBRE = 1     # arbre libre
# Avant que Python ne tourne, les broches du MCP sont en entrée et la
# pull-down force 0 : les HUIT drivers sont excités dès la mise sous tension.
# Le programme écrit ENA = 1 sur les huit dès l'ouverture du bus.
#
# Les moteurs restent EXCITÉS en permanence de la fin de l'initialisation
# jusqu'à un défaut du poste ou l'arrêt du programme (décidé le 2026-10-27) :
# le mandrin doit tenir son angle. Libres avant l'initialisation et en DÉFAUT.

# ── Sens — PAR POSTE ──────────────────────────────────────────────────────
# Niveau de DIR qui fait tourner le mandrin vers sa butée HORAIRE.
# ⚠ À CONFIRMER (test_5_moteur.py) : si un poste part du mauvais côté,
#   inverser SA valeur. En V2 les axes étaient montés en miroir.
# Fille : relevé le 2026-10-28 (test_5). Mère : ⚠ provisoire, à relever au montage.
DIR_VERS_HORAIRE = {POSTE_MERE: 0, POSTE_FILLE: 0}
DIR_VERS_ANTIHORAIRE = {poste: 1 - niveau for poste, niveau in DIR_VERS_HORAIRE.items()}

# Sens dans lequel le bouton ROTATION + fait tourner le mandrin, par poste.
# ROTATION − tourne dans le sens opposé. ⚠ À CHOISIR avec l'opérateur (test_5).
SENS_ROTATION_PLUS = {POSTE_MERE: SENS_HORAIRE, POSTE_FILLE: SENS_HORAIRE}

# Le moteur étant excité en permanence, il n'y a plus de pause après ENA en
# marche. Seule reste la pause DIR → premier pas, faite PAR LE THREAD
# d'impulsions avant son premier pas : la boucle principale ne s'arrête jamais
# (LOGIQUE.md § 2.1). La pause après excitation ne sert qu'à l'initialisation,
# où elle est attendue sans bloquer la boucle.
MOTEUR_ENA_AVANT_DIR_S = 0.010    # laisse le rotor se caler après excitation
MOTEUR_DIR_AVANT_PAS_S = 0.005    # fiche : DIR stable avant le 1er front (mini 5 µs)

MOTEUR_LARGEUR_IMPULSION_US = 50  # µs — état haut de PUL. Fiche : mini 2,5 µs. Le driver
                                  # latche sur le front DESCENDANT (étage non inverseur).


# ═══════════════════════════════════════════════════════════════════════════
#  MOTEURS — GÉOMÉTRIE
# ═══════════════════════════════════════════════════════════════════════════

# DOIT correspondre aux interrupteurs SW5..SW8 des deux drivers (voir la section
# DRIVERS JK-DM860H en fin de fichier). Toute la géométrie en dépend.
# 6400 pas/tr : 0,056° par pas ; à 10°/s, 178 pas/s par moteur.
# Réglé sur les drivers le 2026-10-28.
DRIVER_PAS_PAR_TOUR = 6400

# Pas de réducteur : le moteur entraîne le mandrin en direct.
PAS_PAR_DEGRE = DRIVER_PAS_PAR_TOUR / 360.0

# Plage de rotation butée ANTIHORAIRE ↔ butée HORAIRE attendue, par poste.
# Mesurée à chaque initialisation ; la valeur mesurée est comparée à celle-ci.
# ⚠ À MESURER (test_5_moteur.py, étape 3) — à reprendre à chaque déplacement d'un capteur.
PLAGE_NOMINALE_DEG = {POSTE_MERE: 130.0, POSTE_FILLE: 130.0}

# Écart toléré entre plage mesurée et plage nominale. Au-delà → défaut D9.
PLAGE_TOLERANCE_DEG = 15.0

# ⚠ PROTECTION DU TUYAU DU MANDRIN. Rotation tolérée AU-DELÀ d'une butée sans
#   la voir, avant arrêt et défaut D1 (D8 à l'initialisation). C'est une borne
#   DURE : le thread d'impulsions s'arrête de lui-même. À l'initialisation,
#   avant que la plage soit connue, le mandrin peut parcourir au pire
#   PLAGE_NOMINALE_DEG + MARGE_DEPASSEMENT_DEG depuis son point de départ
#   (accepté le 2026-10-27). ⚠ À VÉRIFIER : ce que le tuyau accepte.
MARGE_DEPASSEMENT_DEG = 10.0

# Butée de départ encore active après cette rotation → défaut D4 (le moteur ne
# tourne pas). Doit couvrir la marge (un mandrin arrêté par D1 peut se trouver
# jusqu'à MARGE_DEPASSEMENT_DEG derrière sa butée, galet enfoncé) et le retard
# d'arrêt. verifier_config() le contrôle.
DEGAGEMENT_MAX_DEG = 20.0

# Au recalage sur une butée, écart entre la position comptée et la position de
# la butée au-delà duquel le journal signale un avertissement (pas perdus ?).
# Pas de défaut : 100 % manuel, on fait confiance à l'opérateur.
ECART_RECALAGE_MAX_DEG = 1.0

# Centrage : le poste est « au centre » à cette tolérance près (recentrage
# inutile, seule l'ouverture du mandrin est faite).
TOLERANCE_CENTRE_DEG = 0.5


# ═══════════════════════════════════════════════════════════════════════════
#  MOTEURS — VITESSES ET RAMPES  (en degrés de mandrin par seconde)
# ═══════════════════════════════════════════════════════════════════════════
# Communes aux deux postes : mêmes moteurs, même mécanique. Converties en pas/s
# plus bas, jamais saisies en pas.
#
#  vitesse
#     │        ┌──────────────────── … tant que le bouton est tenu
#  CRO│       ╱
#     │      ╱  rampe en S (demi-cosinus), DUREE_RAMPE_ROTATION_S
#  DEM│─────╱
#     └──────────────────────────────── temps
#                               ╳ relâchement / butée → arrêt au pas suivant
#
# Pas de rampe d'arrêt sur une rotation : à ces vitesses un pas-à-pas s'arrête
# net sans perdre de pas, et l'arrêt doit être immédiat (précision).

# ── Rotation au maintien (boutons ROTATION + / −) ──────────────────────────
VITESSE_CROISIERE_DEG_S = 10.0      # ⚠ À AJUSTER — demandé le 2026-10-27
VITESSE_DEMARRAGE_DEG_S = 1.0       # ⚠ À AJUSTER — vitesse du premier pas
DUREE_RAMPE_ROTATION_S = 1.0        # ⚠ À AJUSTER — montée douce et longue, DEMARRAGE → CROISIERE

# True  : rampes « en S » (demi-cosinus), pente nulle aux deux bouts : moins
#         d'à-coups, moins de vibrations (choix de la V2, gardé).
# False : rampes droites.
MOTEUR_RAMPES_EN_S = True

# ── Initialisation : deux passes de chaque côté (LOGIQUE.md § 3.1) ─────────
# Passe RAPIDE : trouve la butée grossièrement (rampe de démarrage, pas de
# rampe d'arrêt). Puis RECUL, puis passe LENTE de confirmation, qui fixe la
# position de la butée.
VITESSE_RECHERCHE_RAPIDE_DEG_S = 20.0   # ⚠ À AJUSTER — les deux moteurs ensemble = 711 pas/s,
                                        # au-dessus des 600 pas/s tenus par un thread en V2 :
                                        # surveiller le « retard max » du journal aux essais
VITESSE_RECHERCHE_LENTE_DEG_S = 3.0     # ⚠ À AJUSTER — arrêt en moins de 0,03° sur la butée
RECUL_CONFIRMATION_DEG = 5.0            # recul après la passe rapide : doit relâcher le galet
TOLERANCE_CONFIRMATION_DEG = 10.0       # la passe lente doit retrouver la butée dans
                                        # RECUL + cette tolérance, sinon défaut D8. Couvre
                                        # l'HYSTÉRÉSIS du galet : il se relâche plus tôt qu'il
                                        # ne s'enclenche. 3° ne suffisaient pas sur machine
                                        # (D8 à 8° le 2026-10-28).

# ── Mouvement vers une position (centrage, recentrage sur ACQUITTEMENT) ────
# Rampe en S de montée et de descente, chacune de DUREE_RAMPE_ROTATION_S
# (raccourcies si le trajet est court), arrêt sur le compte de pas.
VITESSE_RECENTRAGE_DEG_S = 10.0         # ⚠ À AJUSTER

# Sens de la première butée recherchée à l'initialisation.
INIT_PREMIER_SENS = SENS_ANTIHORAIRE

# ── Calculés — ne pas modifier ────────────────────────────────────────────
def _pas(degres: float) -> int:
    return round(PAS_PAR_DEGRE * degres)


VITESSE_CROISIERE_SPS = VITESSE_CROISIERE_DEG_S * PAS_PAR_DEGRE
VITESSE_DEMARRAGE_SPS = VITESSE_DEMARRAGE_DEG_S * PAS_PAR_DEGRE
VITESSE_RECHERCHE_RAPIDE_SPS = VITESSE_RECHERCHE_RAPIDE_DEG_S * PAS_PAR_DEGRE
VITESSE_RECHERCHE_LENTE_SPS = VITESSE_RECHERCHE_LENTE_DEG_S * PAS_PAR_DEGRE
VITESSE_RECENTRAGE_SPS = VITESSE_RECENTRAGE_DEG_S * PAS_PAR_DEGRE
VITESSE_MAX_SPS = max(VITESSE_CROISIERE_SPS, VITESSE_RECHERCHE_RAPIDE_SPS, VITESSE_RECENTRAGE_SPS)

PLAGE_NOMINALE_PAS = {poste: _pas(degres) for poste, degres in PLAGE_NOMINALE_DEG.items()}
PLAGE_TOLERANCE_PAS = _pas(PLAGE_TOLERANCE_DEG)
MARGE_DEPASSEMENT_PAS = _pas(MARGE_DEPASSEMENT_DEG)
DEGAGEMENT_MAX_PAS = _pas(DEGAGEMENT_MAX_DEG)
ECART_RECALAGE_MAX_PAS = _pas(ECART_RECALAGE_MAX_DEG)
TOLERANCE_CENTRE_PAS = _pas(TOLERANCE_CENTRE_DEG)
RECUL_CONFIRMATION_PAS = _pas(RECUL_CONFIRMATION_DEG)

# BUDGETS DE PAS — bornes DURES, le thread s'arrête de lui-même au dernier pas.
# Passe rapide : la plage n'est pas encore connue, le mandrin peut être n'importe où.
BUDGET_RECHERCHE_RAPIDE_PAS = {poste: pas + MARGE_DEPASSEMENT_PAS
                               for poste, pas in PLAGE_NOMINALE_PAS.items()}
# Passe lente : la butée est juste derrière le recul.
BUDGET_CONFIRMATION_PAS = RECUL_CONFIRMATION_PAS + _pas(TOLERANCE_CONFIRMATION_DEG)
# En marche, le budget d'une rotation est calculé au départ depuis la position
# (LOGIQUE.md § 6.1) : vers HORAIRE plage + marge − position, vers ANTIHORAIRE
# position + marge.


# ═══════════════════════════════════════════════════════════════════════════
#  TEMPORISATIONS DES ACTIONS  (secondes)
# ═══════════════════════════════════════════════════════════════════════════
# Règle universelle (LOGIQUE.md § 2) : toute action a une durée. Pendant cette
# durée le poste est occupé et ses boutons sont refusés. L'état de
# l'actionneur ne change qu'à la FIN de l'action.

# Séquence de coupe (inchangée depuis la V2) : attente → impulsion EV → attente → fin.
TEMPS_AVANT_COUPE_S = 0.2      # ⚠ À AJUSTER — laisse l'opérateur dégager la main après l'appui
TEMPS_COUPE_S = 0.75           # ⚠ À AJUSTER — EV coupe alimentée (valeur V2)
TEMPS_APRES_COUPE_S = 0.5      # ⚠ À AJUSTER — garantit la lame remontée avant tout nouvel appui

# Mandrin : l'EV bascule immédiatement, l'état « ouvert / fermé » n'est retenu
# qu'après ce temps. Doit couvrir la course complète des mors. Aussi attendu à
# l'initialisation et au recentrage avant toute rotation, si le mandrin était fermé.
TEMPS_MANOEUVRE_MANDRIN_S = 0.5   # ⚠ À AJUSTER — chronométrer (test_4)

# Après une coupe ou une manœuvre du mandrin, les boutons du poste restent
# refusés ce temps-là. Protège contre le double appui.
TEMPS_GARDE_APRES_ACTION_S = 0.3

# Après une rotation : pas de garde (décidé le 2026-10-27), pour que l'opérateur
# puisse ajuster par petits coups. Un nouveau front d'appui stable reste exigé.
TEMPS_GARDE_APRES_ROTATION_S = 0.0


# ═══════════════════════════════════════════════════════════════════════════
#  BOUCLE PRINCIPALE
# ═══════════════════════════════════════════════════════════════════════════
# 250 Hz : latence de décision 4 ms. Coût I2C ≈ 2 lectures + au plus 2
# écritures par tour, ~25 % du bus. Aucune attente bloquante dans la boucle.

FREQUENCE_BOUCLE_HZ = 250
PERIODE_BOUCLE_S = 1.0 / FREQUENCE_BOUCLE_HZ

# Intervalle de bascule du GIL entre threads Python (défaut 5 ms). Réduit pour
# que les threads d'impulsions récupèrent la main vite quand leur pas arrive à
# échéance. Plus important encore en V3 : deux threads tournent ensemble.
PYTHON_SWITCH_INTERVAL_S = 0.0005

# Attente maximale de la fin d'un thread d'impulsions après un ordre d'arrêt
# (défaut, arrêt programme). Un thread s'arrête en moins d'une période de pas.
ARRET_THREAD_MAX_S = 0.2


# ═══════════════════════════════════════════════════════════════════════════
#  BUZZER  (GPIO 26, PWM lgpio)
# ═══════════════════════════════════════════════════════════════════════════
# Non bloquant. Une panne de buzzer ne bloque jamais la machine.
#   appui accepté (BRIDAGE, COUPE, ACQUITTEMENT) . 1 bip court
#   appui ROTATION accepté ....................... AUCUN bip
#   arrivée sur une butée en rotation ............ 1 bip court
#   fin d'action, poste initialisé ............... 2 bips courts
#   appui refusé ................................. 1 bip LONG
#   entrée en défaut ............................. 1 bip très long

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

# Un compteur par bouton (acceptés / refusés), par actionneur et par défaut et
# par poste. Écriture atomique (fichier temporaire + os.replace). Jamais pendant
# un mouvement : une écriture sur carte SD peut bloquer la boucle 100 ms.
CHEMIN_COMPTEURS = _RACINE / "etat" / "compteurs.json"
COMPTEURS_PERIODE_ECRITURE_S = 30.0


# ═══════════════════════════════════════════════════════════════════════════
#  DRIVERS JK-DM860H — RÉGLAGES PHYSIQUES  (documentation, aucune dépendance code)
# ═══════════════════════════════════════════════════════════════════════════
# Moteurs : StepperOnline 24IP65-30 — NEMA 24, 3,0 N·m, 5,0 A / phase, IP65.
# Réglage proposé des DEUX drivers, SW1 → SW8 (1 = ON) :
#   SW1=ON  SW2=ON  SW3=OFF        → 4,28 A RMS / 5,14 A crête (~85 % de 5,0 A ;
#                                    monter à OFF/ON/OFF = 4,86 A RMS si décrochage)
#   SW4=ON                         → PLEIN courant à l'arrêt (réglé par Julien le
#                                    2026-10-28). ⚠ Les moteurs restant excités en
#                                    permanence, surveiller leur échauffement ; repasser
#                                    SW4=OFF (demi-courant) s'ils chauffent trop.
#   SW5=ON  SW6=ON  SW7=OFF SW8=ON → 6400 impulsions/tour (= DRIVER_PAS_PAR_TOUR)
#                                    réglé sur les drivers par Julien le 2026-10-28
# ⚠ Courant (SW1..SW3) : à vérifier sur l'étiquette du driver.
DRIVER_DIP_SWITCH = "11011101"
DRIVER_COURANT_CRETE_A = 5.14

# Ce driver n'a PAS de sortie d'alarme : une panne n'est signalée que par sa
# LED rouge. Les seuls détecteurs logiciels sont D4 (le moteur ne quitte pas sa
# butée de départ) et D1 / D8 (budget de pas épuisé).


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

    def _par_poste(nom: str, table: dict) -> None:
        if set(table) != set(POSTES):
            erreurs.append(f"{nom} : une valeur par poste attendue ({POSTES}), trouvé {sorted(table)}")

    # ── Bits : uniquement ceux qui sont réellement câblés sur le PCB
    ev = {"EV_MANDRIN_MERE": EV_MANDRIN_MERE, "EV_COUPE_MERE": EV_COUPE_MERE,
          "EV_MANDRIN_FILLE": EV_MANDRIN_FILLE, "EV_COUPE_FILLE": EV_COUPE_FILLE}
    for nom, bit in ev.items():
        _dans(nom, bit, set(range(2, 8)))          # relais sur A2..A7 seulement
    _distincts("EV (0x24 A)", ev)

    boutons = {"BTN_BRIDAGE_MERE": BTN_BRIDAGE_MERE, "BTN_ROTATION_PLUS_MERE": BTN_ROTATION_PLUS_MERE,
               "BTN_ROTATION_MOINS_MERE": BTN_ROTATION_MOINS_MERE, "BTN_COUPE_MERE": BTN_COUPE_MERE,
               "BTN_BRIDAGE_FILLE": BTN_BRIDAGE_FILLE, "BTN_ROTATION_PLUS_FILLE": BTN_ROTATION_PLUS_FILLE,
               "BTN_ROTATION_MOINS_FILLE": BTN_ROTATION_MOINS_FILLE, "BTN_COUPE_FILLE": BTN_COUPE_FILLE,
               "BTN_ACQUITTEMENT": BTN_ACQUITTEMENT}
    for nom, entree in boutons.items():
        if not (isinstance(entree, tuple) and len(entree) == 3 and entree[:2] in ENTREES_BOUTONS_CABLEES):
            erreurs.append(f"{nom} = {entree!r} — attendu (MCP, port, bit) parmi les ports "
                           f"{sorted(ENTREES_BOUTONS_CABLEES)}")
        elif entree[2] not in ENTREES_BOUTONS_CABLEES[entree[:2]]:
            erreurs.append(f"{nom} = {entree!r} — bit non câblé sur ce port "
                           f"({list(ENTREES_BOUTONS_CABLEES[entree[:2]])})")

    cap = {"CAP_MERE_HORAIRE": CAP_MERE_HORAIRE, "CAP_MERE_ANTIHORAIRE": CAP_MERE_ANTIHORAIRE,
           "CAP_FILLE_HORAIRE": CAP_FILLE_HORAIRE, "CAP_FILLE_ANTIHORAIRE": CAP_FILLE_ANTIHORAIRE}
    for nom, bit in cap.items():
        _dans(nom, bit, set(range(0, 5)))          # entrées câblées B0..B4
    # Aucune entrée en double entre les 9 boutons et les 4 butées (0x26 port B).
    _distincts("boutons + butées", {**boutons, **{nom: ("0x26", "B", bit) for nom, bit in cap.items()}})

    for nom, bit in (("DIR_MERE", DIR_MERE), ("DIR_FILLE", DIR_FILLE),
                     ("ENA_MERE", ENA_MERE), ("ENA_FILLE", ENA_FILLE)):
        _dans(nom, bit, set(range(0, 8)))
    _distincts("DIR (0x25 A)", {"DIR_MERE": DIR_MERE, "DIR_FILLE": DIR_FILLE})
    _distincts("ENA (0x25 B)", {"ENA_MERE": ENA_MERE, "ENA_FILLE": ENA_FILLE})

    # ── Niveaux logiques et sens
    for nom, val in (("ENA_MOTEUR_EXCITE", ENA_MOTEUR_EXCITE), ("ENA_MOTEUR_LIBRE", ENA_MOTEUR_LIBRE)):
        _dans(nom, val, {0, 1})
    if ENA_MOTEUR_EXCITE == ENA_MOTEUR_LIBRE:
        erreurs.append("ENA_MOTEUR_EXCITE et ENA_MOTEUR_LIBRE identiques")
    for nom, table in (("DIR_VERS_HORAIRE", DIR_VERS_HORAIRE),
                       ("SENS_ROTATION_PLUS", SENS_ROTATION_PLUS),
                       ("PLAGE_NOMINALE_DEG", PLAGE_NOMINALE_DEG)):
        _par_poste(nom, table)
    for poste, niveau in DIR_VERS_HORAIRE.items():
        _dans(f"DIR_VERS_HORAIRE[{poste}]", niveau, {0, 1})
    for poste, sens in SENS_ROTATION_PLUS.items():
        _dans(f"SENS_ROTATION_PLUS[{poste}]", sens, set(SENS))
    _dans("INIT_PREMIER_SENS", INIT_PREMIER_SENS, set(SENS))

    # ── GPIO : aucune broche en double
    gpio = [PUL_MERE, PUL_FILLE, BUZZER_GPIO, *GPIO_RELAIS_LIBRES]
    if len(set(gpio)) != len(gpio):
        erreurs.append(f"GPIO en double parmi PUL / buzzer / relais libres : {gpio}")

    # ── Adresses MCP distinctes
    if len({MCP_RELAIS_ADDR, MCP_DRIVERS_ADDR, MCP_ENTREES_ADDR}) != 3:
        erreurs.append("MCP_RELAIS_ADDR / MCP_DRIVERS_ADDR / MCP_ENTREES_ADDR : trois adresses distinctes attendues")

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
        *((f"PLAGE_NOMINALE_DEG[{poste}]", degres) for poste, degres in PLAGE_NOMINALE_DEG.items()),
        ("PLAGE_TOLERANCE_DEG", PLAGE_TOLERANCE_DEG),
        ("MARGE_DEPASSEMENT_DEG", MARGE_DEPASSEMENT_DEG),
        ("DEGAGEMENT_MAX_DEG", DEGAGEMENT_MAX_DEG),
        ("ECART_RECALAGE_MAX_DEG", ECART_RECALAGE_MAX_DEG),
        ("TOLERANCE_CENTRE_DEG", TOLERANCE_CENTRE_DEG),
        ("VITESSE_CROISIERE_DEG_S", VITESSE_CROISIERE_DEG_S),
        ("VITESSE_DEMARRAGE_DEG_S", VITESSE_DEMARRAGE_DEG_S),
        ("DUREE_RAMPE_ROTATION_S", DUREE_RAMPE_ROTATION_S),
        ("VITESSE_RECHERCHE_RAPIDE_DEG_S", VITESSE_RECHERCHE_RAPIDE_DEG_S),
        ("VITESSE_RECHERCHE_LENTE_DEG_S", VITESSE_RECHERCHE_LENTE_DEG_S),
        ("RECUL_CONFIRMATION_DEG", RECUL_CONFIRMATION_DEG),
        ("TOLERANCE_CONFIRMATION_DEG", TOLERANCE_CONFIRMATION_DEG),
        ("VITESSE_RECENTRAGE_DEG_S", VITESSE_RECENTRAGE_DEG_S),
        ("MOTEUR_LARGEUR_IMPULSION_US", MOTEUR_LARGEUR_IMPULSION_US),
        ("MOTEUR_ENA_AVANT_DIR_S", MOTEUR_ENA_AVANT_DIR_S),
        ("MOTEUR_DIR_AVANT_PAS_S", MOTEUR_DIR_AVANT_PAS_S),
        ("TEMPS_COUPE_S", TEMPS_COUPE_S),
        ("TEMPS_MANOEUVRE_MANDRIN_S", TEMPS_MANOEUVRE_MANDRIN_S),
        ("FREQUENCE_BOUCLE_HZ", FREQUENCE_BOUCLE_HZ),
        ("PYTHON_SWITCH_INTERVAL_S", PYTHON_SWITCH_INTERVAL_S),
        ("ARRET_THREAD_MAX_S", ARRET_THREAD_MAX_S),
        ("COMPTEURS_PERIODE_ECRITURE_S", COMPTEURS_PERIODE_ECRITURE_S),
    ):
        _positif(nom, val)

    for nom, val in (("TEMPS_AVANT_COUPE_S", TEMPS_AVANT_COUPE_S),
                     ("TEMPS_APRES_COUPE_S", TEMPS_APRES_COUPE_S),
                     ("TEMPS_GARDE_APRES_ACTION_S", TEMPS_GARDE_APRES_ACTION_S),
                     ("TEMPS_GARDE_APRES_ROTATION_S", TEMPS_GARDE_APRES_ROTATION_S),
                     ("I2C_RETRIES", I2C_RETRIES)):
        if val < 0:
            erreurs.append(f"{nom} = {val} — doit être positif ou nul")

    if not 50 <= FREQUENCE_BOUCLE_HZ <= 1000:
        erreurs.append(f"FREQUENCE_BOUCLE_HZ = {FREQUENCE_BOUCLE_HZ} — attendu entre 50 et 1000")

    # ── Cohérence des vitesses
    if not VITESSE_DEMARRAGE_DEG_S < VITESSE_CROISIERE_DEG_S:
        erreurs.append("VITESSE_DEMARRAGE_DEG_S doit être < VITESSE_CROISIERE_DEG_S")
    if not VITESSE_RECHERCHE_LENTE_DEG_S < VITESSE_RECHERCHE_RAPIDE_DEG_S:
        erreurs.append("VITESSE_RECHERCHE_LENTE_DEG_S doit être < VITESSE_RECHERCHE_RAPIDE_DEG_S")
    for nom, vitesse in (("VITESSE_RECHERCHE_RAPIDE_DEG_S", VITESSE_RECHERCHE_RAPIDE_DEG_S),
                         ("VITESSE_RECENTRAGE_DEG_S", VITESSE_RECENTRAGE_DEG_S)):
        if vitesse <= VITESSE_DEMARRAGE_DEG_S:
            erreurs.append(f"{nom} doit être > VITESSE_DEMARRAGE_DEG_S (la rampe part de là)")
    if MOTEUR_LARGEUR_IMPULSION_US * 1e-6 >= 0.5 / VITESSE_MAX_SPS:
        erreurs.append("MOTEUR_LARGEUR_IMPULSION_US trop grand pour la vitesse maximale")

    # ── Cohérence de la géométrie
    for poste, degres in PLAGE_NOMINALE_DEG.items():
        if PLAGE_TOLERANCE_DEG >= degres / 2:
            erreurs.append(f"PLAGE_TOLERANCE_DEG >= la moitié de PLAGE_NOMINALE_DEG[{poste}]")
        if RECUL_CONFIRMATION_DEG + TOLERANCE_CONFIRMATION_DEG >= degres / 2:
            erreurs.append(f"RECUL + TOLERANCE_CONFIRMATION >= la moitié de PLAGE_NOMINALE_DEG[{poste}]")
        if DEGAGEMENT_MAX_DEG >= degres - PLAGE_TOLERANCE_DEG:
            erreurs.append(f"DEGAGEMENT_MAX_DEG >= plage minimale acceptée de {poste}")

    # Retard entre l'arrivée sur une butée et l'arrêt du thread : lectures
    # consécutives exigées + une période de boucle, à la vitesse maximale.
    retard_arret_pas = VITESSE_MAX_SPS * (CAPTEUR_LECTURES_ARRET + 1) * PERIODE_BOUCLE_S
    if MARGE_DEPASSEMENT_PAS <= retard_arret_pas:
        erreurs.append(
            f"MARGE_DEPASSEMENT_DEG trop petite : {MARGE_DEPASSEMENT_PAS} pas, le retard d'arrêt "
            f"en demande déjà {retard_arret_pas:.0f}")
    # D4 ne doit pas se déclencher à tort quand le mandrin part de derrière sa
    # butée (après un D1) : marge + retard d'anti-rebond à vitesse maximale.
    degagement_mini = (MARGE_DEPASSEMENT_PAS
                       + VITESSE_MAX_SPS * (ANTI_REBOND_CAPTEUR_S + 2 * PERIODE_BOUCLE_S))
    if DEGAGEMENT_MAX_PAS <= degagement_mini:
        erreurs.append(
            f"DEGAGEMENT_MAX_DEG trop petit : {DEGAGEMENT_MAX_PAS} pas, il en faut plus de "
            f"{degagement_mini:.0f} (marge + retard d'anti-rebond)")
    # Le recul doit pouvoir relâcher le galet avant que D4 ne se déclenche.
    if RECUL_CONFIRMATION_DEG >= DEGAGEMENT_MAX_DEG:
        erreurs.append("RECUL_CONFIRMATION_DEG doit être < DEGAGEMENT_MAX_DEG")

    # ── Confirmation d'arrivée : anti-rebond + lectures d'arrêt doivent tenir
    #    dans CONFIRMATION_CAPTEUR_MAX_S.
    duree_confirmation = ANTI_REBOND_CAPTEUR_S + 3 * PERIODE_BOUCLE_S
    if duree_confirmation >= CONFIRMATION_CAPTEUR_MAX_S:
        erreurs.append(
            f"CONFIRMATION_CAPTEUR_MAX_S = {CONFIRMATION_CAPTEUR_MAX_S} s — trop court : "
            f"l'anti-rebond demande déjà {duree_confirmation:.3f} s")

    if erreurs:
        raise ValueError("config.py :\n  - " + "\n  - ".join(erreurs))
