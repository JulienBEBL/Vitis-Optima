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
| Câblage des boutons | 0x24 B0..B5 + ACQUITTEMENT 0x26 B0 | **relevé le 2026-10-28** : 0x24 B0..B5 + 0x26 A5..A7 (voir LOGIQUE.md § 7) |
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
| Rotation | mouvement d'un capteur à l'autre, sur appui | **maintenu = tourne, relâché = arrêt immédiat**. Rampe de démarrage douce et longue, croisière lente **10°/s** (⚠ à ajuster). Les 2 moteurs peuvent tourner en même temps |
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
| 2026-10-27 | Croisière de rotation : 10°/s. |
| 2026-10-27 | Pas de garde après une rotation (petits coups d'ajustement). |
| 2026-10-27 | Initialisation en deux passes de chaque côté : rapide pour trouver la butée, recul, lente pour la confirmer. |
| 2026-10-27 | Dépassement possible à l'initialisation (plage nominale + marge) accepté. |
| 2026-10-27 | LOGIQUE.md V3 validé (version 3.1). |
| 2026-10-28 | Boutons relevés sur machine : 9 contacts NO, répartis sur 0x24 B, 0x26 A (COUPE mère, ACQUITTEMENT, ROTATION − fille). config.py désigne chaque bouton par (MCP, port, bit). I2C validé (test_1). |
| 2026-10-28 | Montage partiel : moteur et 2 butées du greffon (fille) seuls branchés, EV non raccordées → test_greffon.py (mise en service complète d'un seul poste). |
| 2026-10-28 | Tests lancés depuis Geany (F5) : menus au clavier au lieu des options en ligne de commande. test_5 réécrit en mise en service (moteur ↔ poste, sens, butées, remise à zéro, course), test_6 devient le réglage des vitesses et rampes (recherche vitesse max et rampe min). |
| 2026-10-28 | Tests utilisables depuis Geany : plus besoin de Ctrl+C (qui ferme la fenêtre), résultats enregistrés dans logs/. |
| 2026-10-27 | Trouvé sur banc logiciel : le recul de confirmation est compté depuis le relâchement de la butée (sinon D4 à tort après un D1). |
| 2026-10-27 | ACQUITTEMENT en marche recentre les deux postes ; il rouvre d'abord le mandrin s'il est fermé ; refusé pour un poste occupé. |
| 2026-10-27 | Un poste fait une chose à la fois (§ 4.5). |
| 2026-10-27 | Demi-courant à l'arrêt gardé (SW4 = OFF) : pas besoin du courant plein pendant la coupe. |
| 2026-10-27 | Buzzer en rotation : pas de bip à l'appui, bip long si refusé, bip court sur butée. |
| 2026-10-27 | Validés : ROTATION − sur le MCP 0x26 (fins de course + ACQUITTEMENT) GPA4 / GPA5, sécurité du tuyau (§ 4.3), drivers 6400 pas/tr et 4,28 A RMS (§ 4.4). |

---

## 4. Propositions — validées le 2026-10-27

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
- **Croisière** : **10°/s** (demandé le 2026-10-27).
- **Relâchement** : arrêt au pas suivant. Le relâchement est pris sur la **lecture brute**
  (comme les capteurs en V2), sans attendre l'anti-rebond de 50 ms : à 10°/s, 50 ms
  feraient 0,5° de trop. Latence visée : 4 à 8 ms, soit < 0,1°.
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
| Micropas | **6400 pas/tr** (SW5..SW8 = ON/ON/OFF/ON ⚠ à vérifier sur l'étiquette) | 0,056° par pas ; croisière à 10°/s = **178 pas/s** par moteur, 356 pas/s pour les deux ensemble. La V2 tenait 600 pas/s sur un seul thread : marge suffisante pour deux threads. On peut monter à 12 800 si besoin de plus de douceur, en vérifiant la régularité. |
| Courant | **4,28 A RMS / 5,14 A crête** (SW1..SW3 = ON/ON/OFF) | ≈ 85 % des 5,0 A du moteur : la vitesse est faible, le couple suffit, le moteur chauffe moins. Monter d'un cran si l'axe décroche. |
| Demi-courant à l'arrêt (SW4) | ⚠ question | à l'arrêt, le couple de maintien est divisé par deux : à voir si le mandrin doit tenir son angle pendant la coupe. |

### 4.5 Un poste fait une chose à la fois

Proposition : pendant la manœuvre du mandrin (≈ 0,5 s) et pendant la coupe, la rotation est
refusée ; pendant la rotation, BRIDAGE et COUPE sont refusés.

---

## 5. Questions ouvertes

Toutes tranchées le 2026-10-27 (voir § 3).

## 6. Avancement

- [x] 2026-10-27 — dossier `indus_V3/` créé (copie de la V2, comportement inchangé)
- [x] 2026-10-27 — réponses de Julien consignées (§ 1 à 3)
- [x] 2026-10-27 — propositions § 4 et questions § 5 validées
- [x] 2026-10-27 — `LOGIQUE.md` réécrit pour la V3 (projet 3.0)
- [x] 2026-10-27 — `LOGIQUE.md` validé par Julien (3.1)
- [x] 2026-10-27 — `config.py` écrit pour la V3
- [x] 2026-10-27 — `config.py` validé par Julien
- [x] 2026-10-27 — code (`main.py`, `libs/`) écrit et vérifié sur banc logiciel (45 vérifications)
- [x] 2026-10-27 — scripts de test 1 à 8 adaptés ; 1, 4, 6, 7, 8 et `main.py` exécutés sur banc logiciel
- [x] 2026-10-27 — README réécrit pour la V3
- [ ] Essais machine
