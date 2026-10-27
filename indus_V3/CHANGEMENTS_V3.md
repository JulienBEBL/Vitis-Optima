# Vitis Optima — indus V3 · Changements par rapport à la V2

Point de départ : copie de `indus_V2/` au commit `f529fc0` (2026-10-14).
`indus_V2/` reste dans le dépôt pour l'historique ; la machine a été démontée pour la V3,
la V2 sera obsolète.

Ce fichier suit, étape par étape, ce qui change entre la V2 et la V3. Une fois une
modification validée et codée, elle est reportée dans `LOGIQUE.md` (la référence) et
`config.py` ; ce fichier garde l'historique et le pourquoi.

Méthode : questions → décisions → `LOGIQUE.md` → `config.py` → code → tests, chaque étape
validée avant la suivante.

⚠ = à mesurer ou à attribuer pendant les essais.

---

## 1. Matériel

| Sujet | V2 | V3 |
|---|---|---|
| PCB | « indus V1 » Clean & Protech, MCP 0x24 / 0x25 / 0x26 | **inchangé** |
| Postes | mère + fille, liés par l'ordre maître / esclave | mère + fille, **totalement indépendants** (électrique, mécanique, logique) |
| Bridage | vérin de bridage, EV 1 bobine | **mandrin pneumatique** (EV 1 bobine) : il serre la branche et fait office de bridage. Tourne avec le moteur, **sans joint tournant** pneumatique |
| Relais | 4 relais câblés sur A2..A5 | **les 4 mêmes** : mandrin mère, coupe mère, mandrin fille, coupe fille. ⚠ attribution à refaire (test_4) |
| Polarité mandrin | bit 0 = débridé | **bit 0 = mandrin OUVERT** (état sûr), bit 1 = mandrin fermé |
| Boutons par poste | 3 : BRIDAGE, COUPE, POSITION | **4 : BRIDAGE, ROTATION +, ROTATION −, COUPE** → 8 boutons + ACQUITTEMENT. ⚠ attribution (test_2) |
| Câblage des 2 nouveaux | — | proposé : **0x26 GPA4 et GPA5** (voir § 4.1) |
| Mécanique | moteur entre 2 positions (coupe / ligaturage) | moteur à arbre **parallèle au sol**, sur un **guide de translation déplacé à la main** (aucun capteur) ; il fait tourner le mandrin |
| Fins de course | 2 par axe : COUPE / LIGATURAGE | 2 par axe, déplacées : **butées HORAIRE / ANTIHORAIRE** de la rotation du mandrin, plage ≈ 130° ⚠. Même câblage, contact NO actif bas. ⚠ attribution (test_3) |
| Moteurs | NEMA 34 | **NEMA 24 StepperOnline 24IP65-30** : 3 N·m, 5,0 A, IP65. Pas de réducteur |
| Drivers | JK-DM860H, 1600 pas/tr, 5,43 A RMS | **mêmes drivers**, micropas et courant à revoir (§ 4.4) |
| Maintien | moteurs excités en position | **inchangé** : toujours excités en position |
| Capteurs ajoutés | — | **aucun** |

## 2. Logique

| Sujet | V2 | V3 |
|---|---|---|
| Cycle | bridage → coupe → POSITION maître puis esclave → ouverture des 2 pinces → ACQUITTEMENT | **par poste, indépendant, au choix de l'opérateur** : BRIDAGE (mandrin fermé) → déplacement manuel du bloc → rotation à la demande → COUPE → recul manuel du bloc → BRIDAGE (mandrin ouvert, branche récupérée) |
| Maître / esclave | fille maître, I7, I9, retard sens aller | **supprimé** |
| Enchaînement | aucun automatisme | **aucun automatisme** |
| Rotation | mouvement d'un capteur à l'autre, sur appui | **maintenu = tourne, relâché = arrêt immédiat**. Rampe de démarrage douce et longue, croisière lente (≈ 150° en 10 s, ⚠ à ajuster). Les 2 moteurs peuvent tourner en même temps |
| Butées | — | arrêt **sur le capteur** ; sur un capteur, seul le sens opposé est accepté |
| Rotation autorisée | — | **tout le temps, sauf pendant la séquence de coupe** (mandrin ouvert ou fermé) |
| Coupe | séquence avant → impulsion → après | **même séquence** ; **interdite si le mandrin du poste est ouvert** (poste par poste) |
| Démarrage | ACQUITTEMENT → esclave puis maître en position coupe | **ACQUITTEMENT** → pour chaque poste, en même temps : recherche lente des **deux butées**, puis **centrage** au milieu de la plage mesurée |
| Retour au centre | — | **uniquement sur appui ACQUITTEMENT**. Jamais automatique en fin de cycle : l'opérateur gère |
| Défauts | globaux, sortie par ACQUITTEMENT | **par poste** : un défaut fille n'arrête pas la mère. ACQUITTEMENT acquitte les postes en défaut. Les défauts du bus I2C (D6, D7) restent forcément globaux |
| Translation | — | aucune mesure : **on fait confiance à l'opérateur** (bloc reculé avant coupe et avant débridage) |
| Sens inversé | proposition d'un défaut | **refusé** : 100 % manuel |

## 3. Décisions

| Date | Décision |
|---|---|
| 2026-10-27 | Partir d'une copie de la V2 plutôt que d'une page blanche. |
| 2026-10-27 | PCB, 3 MCP, 4 relais et drivers inchangés. Aucun capteur ajouté. Pas de réducteur. |
| 2026-10-27 | Plus de maître / esclave : deux postes totalement indépendants, défauts par poste. |
| 2026-10-27 | Aucun enchaînement automatique d'actions. |
| 2026-10-27 | Le mandrin fait office de bridage ; relais à 0 = mandrin ouvert. |
| 2026-10-27 | Rotation au maintien, arrêt immédiat au relâchement, arrêt sur capteur. |
| 2026-10-27 | Initialisation sur ACQUITTEMENT : deux butées puis centrage, les deux postes en même temps. |
| 2026-10-27 | Retour au centre seulement sur ACQUITTEMENT. |
| 2026-10-27 | Pas de défaut « sens inversé ». |

---

## 4. Propositions — en attente de validation (2026-10-27)

### 4.1 Câblage des 2 nouveaux boutons → 0x26 GPA4 et GPA5

Ce qui reste sur le PCB : le 0x24 port B n'expose que B0..B5 (déjà pris) ; le 0x26 port B
a B0 (ACQUITTEMENT) et B1..B4 (capteurs) ; le **0x26 port A a GPA4..GPA7 câblés et libres**.

- **ROTATION − mère → 0x26 GPA4**, **ROTATION − fille → 0x26 GPA5**.
- Les 6 boutons existants restent où ils sont ; l'ancien POSITION devient ROTATION +.
- Coût nul : la boucle lit déjà GPIOA + GPIOB du 0x26 en une seule transaction.
- L'attribution exacte se fait avec `test_2_boutons.py`, comme en V2.

### 4.2 Rotation au maintien

- **Démarrage** : le moteur part d'une vitesse très basse et monte en S jusqu'à la croisière
  sur ≈ 1 s (⚠ à régler).
- **Croisière** : 150° en 10 s = 15°/s.
- **Relâchement** : arrêt au pas suivant. Le relâchement est pris sur la **lecture brute**
  (comme les capteurs en V2), sans attendre l'anti-rebond de 50 ms : à 15°/s, 50 ms
  feraient 0,75° de trop. Latence visée : 4 à 8 ms, soit ≈ 0,1°.
  À cette vitesse, un pas-à-pas s'arrête net sans perdre de pas : pas besoin de rampe d'arrêt.
- **Butée** : capteur atteint → arrêt immédiat (sans surcourse), seul le sens opposé est
  accepté tant que le capteur est actif.
- **+ et − en même temps** : arrêt, rien ne tourne.

### 4.3 Sécurité du tuyau du mandrin

Sans joint tournant, un capteur mort laisserait le mandrin tourner au-delà de la plage. Le
programme compte les pas : la position est connue depuis l'initialisation, et recalée à
chaque passage sur une butée.

- Si le compteur dépasse la plage mesurée + une marge (≈ 10°) sans voir le capteur →
  **arrêt et défaut du poste** (équivalent du D1 de la V2).
- À l'initialisation, la plage mesurée est comparée à la plage attendue (≈ 130° ± tolérance)
  → hors tolérance : **défaut du poste**.

### 4.4 Drivers

| Réglage | Proposé | Pourquoi |
|---|---|---|
| Micropas | **6400 pas/tr** (SW5..SW8 = ON/ON/OFF/ON ⚠ à vérifier sur l'étiquette) | 0,056° par pas ; croisière à 15°/s = **267 pas/s** par moteur, 534 pas/s pour les deux ensemble. La V2 tenait 600 pas/s sur un seul thread : marge suffisante pour deux threads. On peut monter à 12 800 si besoin de plus de douceur, en vérifiant la régularité. |
| Courant | **4,28 A RMS / 5,14 A crête** (SW1..SW3 = ON/ON/OFF) | ≈ 85 % des 5,0 A du moteur : la vitesse est faible, le couple suffit, le moteur chauffe moins. Monter d'un cran si l'axe décroche. |
| Demi-courant à l'arrêt (SW4) | ⚠ question | à l'arrêt, le couple de maintien est divisé par deux : à voir si le mandrin doit tenir son angle pendant la coupe. |

### 4.5 Un poste fait une chose à la fois

Proposition : pendant la manœuvre du mandrin (≈ 0,5 s) et pendant la coupe, la rotation est
refusée ; pendant la rotation, BRIDAGE et COUPE sont refusés.

---

## 5. Questions ouvertes (2026-10-27)

1. ACQUITTEMENT en marche (retour au centre) : les deux postes ensemble ? Autorisé mandrin
   fermé ? Refusé pour un poste occupé (coupe, rotation) ?
2. Valider § 4.5 : BRIDAGE et COUPE refusés pendant la rotation, rotation refusée pendant la
   manœuvre du mandrin ?
3. SW4 : demi-courant à l'arrêt ou pleine intensité pour tenir le mandrin pendant la coupe ?
4. Buzzer en rotation : pas de bip à l'appui (il bipperait sans cesse) ; bip long si refusé ;
   un bip court à l'arrivée sur une butée ?
5. Valider § 4.1 (câblage), § 4.3 (sécurité du tuyau), § 4.4 (drivers).

## 6. Avancement

- [x] 2026-10-27 — dossier `indus_V3/` créé (copie de la V2, comportement inchangé)
- [x] 2026-10-27 — réponses de Julien consignées (§ 1 à 3)
- [ ] Propositions § 4 et questions § 5 validées
- [ ] `LOGIQUE.md` réécrit pour la V3 et validé
- [ ] `config.py` mis à jour et validé
- [ ] Code (`main.py`, `libs/`)
- [ ] Scripts de test (`tests/`)
- [ ] Essais machine
