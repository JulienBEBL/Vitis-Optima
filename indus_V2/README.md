# Vitis Optima — indus V2

Programme de pilotage du prototype indus V2 : deux postes symétriques (mère, fille),
chacun avec un bridage, une coupe et un axe NEMA 34. Raspberry Pi 5, Python 3.11+.

- **LOGIQUE.md** — la logique : états, transitions, interlocks, défauts, mapping E/S.
- **config.py** — le seul fichier à modifier : broches, durées, vitesses.
- **main.py** — le programme.

---

## 1. Installation sur la Raspberry Pi

```bash
sudo apt install python3-lgpio python3-smbus2
```

- I2C activé : `sudo raspi-config` → Interface Options → I2C.
- L'utilisateur doit être dans les groupes `gpio` et `i2c` (c'est le cas de l'utilisateur par défaut).
- Vérifier la présence des trois MCP : `sudo i2cdetect -y 1` → `24`, `25`, `26`.

## 2. Lancement

```bash
cd indus_V2
python3 main.py
```

Arrêt : `Ctrl+C`. Toute sortie du programme, y compris sur erreur, remet les relais à 0
(débridé, lames hautes) et les moteurs libres.

Le service systemd n'est pas encore basculé sur ce programme (phase 3).

## 3. Utilisation

| Étape | Ce qui se passe |
|---|---|
| Mise sous tension | Relais à 0, moteurs libres. La machine attend. |
| **ACQUITTEMENT** | Initialisation : l'esclave revient en position coupe, puis le maître. Double bip = machine prête. |
| **BRIDAGE** | Bascule bridé ↔ débridé. En position coupe seulement. |
| **COUPE** | Attente, impulsion de coupe, attente. En position coupe seulement, bridé ou non. |
| **POSITION** | Bascule position coupe ↔ position ligaturage. Il faut être bridé pour partir en ligaturage. |

Ordre entre les postes (`MOTEUR_MAITRE` dans config.py) :
- **aller** : le maître d'abord ; l'esclave est refusé tant que le maître n'est pas arrivé
  depuis `RETARD_SENS_ALLER_S` ;
- **retour** : l'esclave d'abord ; le maître est refusé tant que l'esclave n'est pas revenu.

En position ligaturage, COUPE et BRIDAGE sont refusés. Tout appui pendant une action est refusé.

| Son | Signification |
|---|---|
| 1 bip court | appui accepté |
| 2 bips courts | action terminée, ou machine prête |
| 1 bip long | appui refusé (le motif est dans le journal) |
| 1 bip très long | défaut |

**En défaut** : relais à 0, moteurs libres, seul ACQUITTEMENT répond. Il relance une
initialisation complète.

---

## 4. Procédure de test sur machine

Faire les étapes dans l'ordre. Ne passer à la suivante que si la précédente est bonne.
Chaque script remet tout en sécurité en sortant, y compris sur `Ctrl+C`.
Arrêt d'urgence à portée de main dès l'étape 4.3.

### 4.1 Entrées — rien ne bouge

| # | Commande | À vérifier | Si c'est faux |
|---|---|---|---|
| 1 | `python3 tests/test_1_i2c.py` | 3 × « ✓ » et 3 × « configuration conforme » | câblage I2C, `i2cdetect -y 1` |
| 2 | `python3 tests/test_2_boutons.py` | Chaque bouton allume **son** voyant ; un appui maintenu compte **un** appui | échanger les `BTN_*` |
| 3 | `python3 tests/test_3_capteurs.py` | Pour chaque axe, à la main : hors position → deux « ·· » ; en coupe → seul COUPE allumé ; en ligaturage → seul LIGATURAGE allumé | échanger les `CAP_*` |
| 4 | idem, galet actionné, **débrancher le connecteur** | Le voyant **s'éteint** (repli sûr) | câblage NF au lieu de NO, ou `CAPTEURS_ACTIFS_BAS` |

### 4.2 Sorties — les vérins bougent

Air comprimé branché, mains hors des lames.

| # | Commande | À vérifier | Si c'est faux |
|---|---|---|---|
| 5 | `python3 tests/test_4_relais.py`, touches 1 à 4 | Chaque touche fait bouger **le bon** vérin | échanger les `EV_*` |
| 6 | idem | Bit à 0 = débridé / lame haute ; bit à 1 = bridé / lame basse | inverser AIR 1 / AIR 2 |
| 7 | idem, chronomètre | Durée de la course du vérin de bridage | `TEMPS_MANOEUVRE_BRIDAGE_S` |
| 8 | touches `c` et `f` | Coupe franche, lame remontée avant « séquence terminée » | `TEMPS_COUPE_S`, `TEMPS_APRES_COUPE_S` |

### 4.3 Moteurs à vide — sans bois

Avant tout : **lire l'étiquette des drivers** et confirmer `DRIVER_PAS_PAR_TOUR`.

| # | Commande | À vérifier | Si c'est faux |
|---|---|---|---|
| 9 | `python3 tests/test_5_moteur.py`, axe mère, étape 1 | **L'axe mère** tourne (pas la fille), **vers le bon côté** | `DIR_MERE`, `ENA_MERE`, `PUL_MERE` ; puis `DIR_VERS_*` |
| 10 | étape 2 | Arrêt net sur la fin de course, à vitesse lente | test_3 |
| 11 | étape 3, plusieurs allers-retours | Mouvement sans à-coup, arrêt sur fin de course | vitesses et rampes |
| 12 | idem, axe fille | idem | idem avec `*_FILLE` |
| 13 | `python3 tests/test_6_course.py`, chaque axe | Valeur proposée pour la course ; aller et retour cohérents | reporter `MOTEUR_COURSE_DEGRES` |
| 14 | test_5 étape 3, en montant `MOTEUR_VITESSE_MAX_SPS` puis `ACCEL` / `DECEL` | Jusqu'au décrochage (bruit, perte de pas), puis −30 % | — |

Si `main.py` ou un test refuse de démarrer avec « profil impossible », c'est que
l'accélération et la décélération ne tiennent pas dans la course : le message dit quoi ajuster.

### 4.4 Cycle complet — `python3 main.py`, sans bois puis avec bois

| # | Action | Attendu |
|---|---|---|
| 15 | Démarrage | Relais à 0, rien ne bouge. Un appui sur un bouton d'action → bip long. |
| 16 | ACQUITTEMENT, un axe laissé en pleine course | Esclave puis maître reviennent en coupe, le premier en recherche lente. Double bip. |
| 17 | POSITION maître, non bridé | Refusé (I6) |
| 18 | BRIDAGE maître, ré-appui immédiat | Premier accepté ; ré-appui refusé (I2) ; double bip à la fin |
| 19 | COUPE maître, plusieurs fois | Chaque coupe complète, double bip ; appuis pendant la coupe refusés |
| 20 | POSITION esclave (bridé), maître en coupe | Refusé (I7) |
| 21 | POSITION maître | Le maître part en ligaturage ; double bip à l'arrivée |
| 22 | COUPE et BRIDAGE maître en ligaturage | Refusés (I4, I5) |
| 23 | POSITION esclave aussitôt, puis après `RETARD_SENS_ALLER_S` | Refusé, puis accepté |
| 24 | POSITION maître, esclave en ligaturage | Refusé (I8) |
| 25 | POSITION esclave, puis POSITION maître | Retour dans cet ordre |
| 26 | `Ctrl+C` pendant un mouvement | Le moteur s'arrête, relais à 0, moteurs libres |

Après chaque action refusée, le motif est dans le journal.

### 4.5 Cas de défaut — `python3 main.py`

Pour chacun : bip très long ; relais à 0 (débridé, lames hautes) ; moteurs libres ;
ligne `DÉFAUT Dx` dans le journal ; seul ACQUITTEMENT répond et relance l'initialisation.

| # | Provoquer | Attendu |
|---|---|---|
| 27 | Débrancher la fin de course **ligaturage** d'un axe, puis l'envoyer en ligaturage | **D1**. L'axe dépasse la position nominale d'au plus `MOTEUR_MARGE_DEG`. Rebrancher, ACQUITTEMENT → l'axe revient en coupe. |
| 28 | Couper la puissance d'un driver, puis POSITION | **D4** en moins de `MOTEUR_DEGAGEMENT_MAX_DEG` |
| 29 | Axe en position coupe, débrancher sa fin de course coupe | **D5** |
| 30 | Axe en position coupe, shunter sa fin de course ligaturage | **D2** |
| 31 | Axe en pleine course, fin de course coupe débranchée, ACQUITTEMENT | **D8** après la recherche lente bornée. ⚠ Sans fin de course coupe, la recherche peut dépasser la position coupe de `MOTEUR_COURSE_DEGRES` + `MOTEUR_MARGE_DEG` (≈ 100°). Ne faire ce test que si la mécanique le permet. |

D3 (cible déjà active au départ), D6 (bus I2C) et D7 (MCP qui perd sa configuration) ne
se provoquent pas proprement sur machine : ils ont été vérifiés sur banc logiciel.

---

## 5. Journal et compteurs

- **Journal** : `logs/vitis_optima.log`, 5 archives de 1 Mo. Démarrage, initialisation,
  actions terminées, appuis refusés avec leur motif, défauts.
  Suivre en direct : `tail -f logs/vitis_optima.log`.
- **Compteurs** : `etat/compteurs.json`. Par bouton (acceptés / refusés), par actionneur,
  par code de défaut. Pas de compteur global. Écrit toutes les 30 s hors mouvement, à
  chaque défaut et à l'arrêt.

## 6. Défauts

| Code | Signification | Que vérifier |
|---|---|---|
| D1 | Fin de course cible non atteinte, budget de pas épuisé | Fil ou connecteur de la fin de course cible ; axe bloqué ; course réelle > `MOTEUR_COURSE_DEGRES` + marge |
| D2 | Deux fins de course actives sur le même axe | Court-circuit de câblage ; galet déréglé |
| D3 | Fin de course cible déjà active au départ | Capteur collé ; axe déplacé à la main |
| D4 | Fin de course de départ toujours active : le moteur ne tourne pas | Puissance du driver ; LED rouge du driver ; ENA ; accouplement |
| D5 | Fin de course perdue à l'arrêt, ou non confirmée à l'arrivée | Galet desserré ; vibration ; connecteur ; `TOLERANCE_PERTE_CAPTEUR_S` |
| D6 | Erreur de bus I2C | Nappe, alimentation des MCP, parasites |
| D7 | Un MCP23017 a perdu sa configuration deux fois de suite | Parasites des drivers de puissance, découplage, masse |
| D8 | Initialisation : position coupe non atteinte | Comme D1, pour la fin de course coupe |

## 7. Valeurs à confirmer

Toutes sont dans `config.py`, marquées ⚠ :

| Valeur | Comment | Étape |
|---|---|---|
| `BTN_*` | test_2 | 2 |
| `CAP_*`, `CAPTEURS_ACTIFS_BAS` | test_3 | 3, 4 |
| `EV_*` | test_4 | 5, 6 |
| `TEMPS_MANOEUVRE_BRIDAGE_S`, `TEMPS_COUPE_S`, `TEMPS_AVANT_COUPE_S`, `TEMPS_APRES_COUPE_S` | test_4 | 7, 8 |
| `DRIVER_PAS_PAR_TOUR` | étiquette du driver | avant 9 |
| `DIR_MERE`, `DIR_FILLE`, `DIR_VERS_COUPE`, `DIR_VERS_LIGATURAGE` | test_5 | 9, 12 |
| `MOTEUR_COURSE_DEGRES`, `MOTEUR_REDUCTION` | test_6 | 13 |
| `MOTEUR_VITESSE_MAX_SPS`, `MOTEUR_ACCEL_SPS2`, `MOTEUR_DECEL_SPS2` | test_5 | 14 |
| `MOTEUR_MAITRE`, `RETARD_SENS_ALLER_S` | observation, avec bois | 21–25 |
