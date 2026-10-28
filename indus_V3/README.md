# Vitis Optima — indus V3

Programme de pilotage du prototype indus V3 : deux postes **mère** et **fille**, totalement
indépendants. Chacun a un mandrin pneumatique (le bridage), une coupe et un moteur NEMA 24
qui fait tourner le mandrin entre deux butées. Raspberry Pi 5, Python 3.11+.

- **LOGIQUE.md** — la logique : états, interlocks, défauts, mapping E/S.
- **config.py** — le seul fichier à modifier : broches, durées, vitesses.
- **CHANGEMENTS_V3.md** — ce qui a changé depuis la V2, et pourquoi.
- **main.py** — le programme.

> **V3 codée, pas encore essayée sur la machine.** Vérifiée sur banc logiciel (faux
> matériel, hors dépôt). Faire la procédure du § 4 dans l'ordre avant tout usage.

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
cd indus_V3
python3 main.py
```

Arrêt : `Ctrl+C`. Toute sortie du programme, y compris sur erreur, remet les relais à 0
(mandrins ouverts, lames hautes) et les moteurs libres.

Le service systemd n'est pas encore basculé sur ce programme.

## 3. Utilisation

Les deux postes fonctionnent chacun de son côté. Rien ne s'enchaîne tout seul.

| Bouton | Ce qui se passe |
|---|---|
| **ACQUITTEMENT** (au démarrage, ou après un défaut) | Pour chaque poste : ouverture du mandrin, recherche des deux butées (passe rapide, recul, passe lente de chaque côté), centrage. Double bip = poste prêt. |
| **ACQUITTEMENT** (en marche) | Retour au centre des deux mandrins. Le mandrin s'ouvre d'abord s'il est fermé. Refusé pour un poste occupé. |
| **BRIDAGE** | Ferme ou ouvre le mandrin, à n'importe quel angle. |
| **ROTATION + / −** | Le mandrin tourne **tant que le bouton est tenu** : départ doux, croisière lente, arrêt immédiat au relâchement. Arrêt sur une butée (bip court) ; ensuite seul le sens opposé est accepté. |
| **COUPE** | Attente, impulsion de coupe, attente. **Refusée mandrin ouvert.** |

Cycle type d'un poste : BRIDAGE → avancer le bloc à la main → ROTATION ± → COUPE → reculer le
bloc à la main → BRIDAGE (mandrin ouvert, branche récupérée).

Un poste fait une chose à la fois : pendant une rotation, BRIDAGE et COUPE sont refusés ;
pendant une coupe ou une manœuvre du mandrin, la rotation est refusée.

| Son | Signification |
|---|---|
| 1 bip court | appui accepté ; arrivée sur une butée en rotation |
| aucun bip | appui ROTATION accepté |
| 2 bips courts | action terminée, ou poste prêt |
| 1 bip long | appui refusé (le motif est dans le journal) |
| 1 bip très long | défaut |

**En défaut** : le poste en défaut a ses relais à 0 et son moteur libre ; **l'autre poste
continue**. ACQUITTEMENT relance l'initialisation du poste en défaut.

---

## 4. Procédure de test sur machine

Tous les tests se lancent **depuis Geany (F5)** : aucune option en ligne de commande, les
choix se font par des menus au clavier. Chaque test se termine seul et remet tout en sécurité
(relais à 0, moteurs libres). Dans le terminal de Geany, `Ctrl+C` ferme la fenêtre : le garder
pour l'urgence. Les résultats des tests 2, 5, 6, 7 et 8 sont aussi enregistrés dans `logs/`.

Faire les étapes dans l'ordre. Ne passer à la suivante que si la précédente est bonne.
Arrêt d'urgence à portée de main dès le § 4.3. Mandrins vides jusqu'au § 4.4.

### 4.1 Entrées — rien ne bouge

| # | Test | À vérifier | Si c'est faux |
|---|---|---|---|
| 1 | `test_1_i2c.py` ✓ validé le 2026-10-28 | 3 × « ✓ » et 3 × « configuration conforme » | câblage I2C, `i2cdetect -y 1` |
| 2 | `test_2_boutons.py`, menu 1 VALIDATION | Le programme nomme les 9 boutons, tu appuies (et maintiens 2 s les 4 ROTATION) ; « TOUT EST BON » à la fin | menu 2 ATTRIBUTION, recopier les `BTN_*` proposés |
| 3 | `test_3_capteurs.py`, menu 2 ATTRIBUTION | Les 4 butées, HORAIRE / ANTIHORAIRE **vues du côté opérateur** ; contact NO | recopier les `CAP_*` proposés |
| 4 | `test_3_capteurs.py`, menu 1 APERÇU, galet actionné, **débrancher le connecteur** | Le voyant **s'éteint** (repli sûr) | câblage NF au lieu de NO |

### 4.2 Sorties — les vérins bougent

Air comprimé branché, mains hors des lames et des mandrins.

| # | Test | À vérifier | Si c'est faux |
|---|---|---|---|
| 5 | `test_4_relais.py` | Chaque relais fait bouger **le bon** organe | recopier les `EV_*` proposés |
| 6 | idem | Relais à 1 = mandrin **fermé** / lame **basse** | croiser AIR 1 / AIR 2 |
| 7 | idem, essai libre, chronomètre | Durée de fermeture du mandrin ; coupe franche | `TEMPS_MANOEUVRE_MANDRIN_S`, `TEMPS_COUPE_S`, `TEMPS_APRES_COUPE_S` |

### 4.3 Moteurs — mandrins vides

Avant tout : **régler et vérifier les DIP des drivers** (6400 pas/tr, 4,28 A RMS, demi-courant
à l'arrêt : `DRIVER_DIP_SWITCH` dans config.py).

`test_5_moteur.py` — mise en service, en quatre étapes enchaînées (le menu permet de
reprendre à une étape) :

| # | Étape | À vérifier | Le test propose |
|---|---|---|---|
| 8 | 1 — quel moteur est qui | Chaque driver fait un petit aller-retour lent : tu dis quel mandrin a tourné et dans quel sens | `PUL_*` / `DIR_*` / `ENA_*` à échanger, `DIR_VERS_HORAIRE` |
| 9 | 2 — butées | Rotation vers HORAIRE puis ANTIHORAIRE : la bonne butée arrête le moteur | `CAP_*` à échanger |
| 10 | 3 — remise à zéro et course totale | Initialisation réelle répétée : plage stable, écart passe rapide / lente faible | `PLAGE_NOMINALE_DEG` |
| 11 | 4 — boutons ROTATION ± | Départ doux, croisière, **arrêt net au relâchement**, arrêt sur butée ; sens de ROTATION + | `SENS_ROTATION_PLUS` |

`test_6_reglage.py` — réglage fin, par un menu ; le critère est l'**écart de recalage** à
chaque arrivée sur une butée (quelques centièmes de degré = bon ; il grandit un peu avec la
vitesse, par le retard de détection ; un décrochage le fait sauter au-delà de 1°) :

| # | Menu | À vérifier | Le test propose |
|---|---|---|---|
| 12 | 2 essai ROTATION, 3 essai RECENTRAGE | Mouvements doux, sans à-coup ni bruit de décrochage ; écart faible | — |
| 13 | 4 recherche VITESSE MAX | La croisière monte de 25 % par palier jusqu'au premier raté | `VITESSE_RECHERCHE_RAPIDE_DEG_S` = 70 % du dernier palier réussi |
| 14 | 5 recherche RAMPE MIN | À la vitesse de passe rapide, la rampe raccourcit jusqu'au premier raté | `DUREE_RAMPE_ROTATION_S` = 1,5 × la plus courte qui tient |
| 15 | 1 modifier un réglage, puis 2 / 3 | Croisière et démarrage au goût de l'opérateur, **avec une branche** | `VITESSE_CROISIERE_DEG_S`, `VITESSE_DEMARRAGE_DEG_S` |

| # | Test | À vérifier | Si c'est faux |
|---|---|---|---|
| 16 | `test_7_rodage.py` | Les deux moteurs ensemble ; écart de recalage stable ; retard max < 2 ms. Arrêt anticipé : ACQUITTEMENT | courant, rampe, vitesses (test_6) |

### 4.4 Cycle complet

| # | Action | Attendu |
|---|---|---|
| 17 | `test_8_cycle.py`, sans branche | Cycles complets des deux postes ensemble, sans défaut ni refus inattendu |
| 18 | `main.py`, démarrage | Relais à 0, rien ne bouge. Un appui sur un bouton d'un poste → bip long (I1). |
| 19 | ACQUITTEMENT | Les deux postes s'initialisent ensemble ; double bip chacun |
| 20 | COUPE, mandrin ouvert | Refusée (I3) — sur ce poste seulement |
| 21 | BRIDAGE, puis ROTATION + tenu, relâché | Mandrin fermé ; le mandrin tourne, s'arrête net |
| 22 | ROTATION tenu jusqu'à la butée, puis encore ROTATION dans le même sens | Arrêt sur la butée, bip court ; puis refusé (I4) ; le sens opposé repart |
| 23 | COUPE pendant une rotation, ROTATION pendant une coupe | Refusés (I2) |
| 24 | ROTATION mère et fille en même temps | Les deux tournent |
| 25 | ACQUITTEMENT, mandrin fermé | Le mandrin s'ouvre, puis revient au centre |
| 26 | `Ctrl+C` pendant une rotation | Le moteur s'arrête, relais à 0, moteurs libres |

### 4.5 Cas de défaut — `main.py`

Pour chacun : bip très long ; relais du poste à 0 ; son moteur libre ; ligne `DÉFAUT Dx [poste]`
dans le journal ; **l'autre poste continue** ; ACQUITTEMENT relance l'initialisation du poste.

| # | Provoquer | Attendu |
|---|---|---|
| 27 | Débrancher une butée, puis tourner vers elle en tenant ROTATION | **D1** : le mandrin dépasse la position de la butée d'au plus `MARGE_DEPASSEMENT_DEG`. ⚠ Vérifier d'abord que le tuyau l'accepte. |
| 28 | Couper la puissance d'un driver, puis tourner en partant d'une butée | **D4** en moins de `DEGAGEMENT_MAX_DEG` |
| 29 | Mandrin arrêté sur une butée, débrancher cette butée | **D5** |
| 30 | Shunter les deux butées d'un poste | **D2** |
| 31 | Débrancher une butée, puis ACQUITTEMENT | **D8**. ⚠ Le mandrin peut parcourir jusqu'à la plage + la marge (≈ 140°) avant l'arrêt. |

D6 (bus I2C), D7 (MCP qui perd sa configuration) et D9 (plage incohérente) ne se provoquent
pas proprement sur machine : ils ont été vérifiés sur banc logiciel.

---

## 5. Journal et compteurs

- **Journal** : `logs/vitis_optima.log`, 5 archives de 1 Mo. Démarrage, initialisations (plage
  mesurée, écart passe rapide / passe lente), actions terminées, appuis refusés avec leur
  motif, avertissements de recalage, défauts. Suivre en direct : `tail -f logs/vitis_optima.log`.
- **Compteurs** : `etat/compteurs.json` (version 3). Par bouton (acceptés / refusés), par
  actionneur, par code de défaut et par poste. Écrit toutes les 30 s hors mouvement, à chaque
  défaut et à l'arrêt. Les scripts de test ne comptent pas.

## 6. Défauts

| Code | Signification | Que vérifier |
|---|---|---|
| D1 | Butée non vue : la rotation a dépassé la plage + la marge | Fil ou connecteur de la butée ; pas perdus |
| D2 | Deux butées actives sur le même poste | Court-circuit ; galet déréglé |
| D4 | Butée de départ toujours active : le moteur ne tourne pas | Puissance du driver ; LED rouge ; ENA ; accouplement |
| D5 | Butée inattendue, perdue à l'arrêt, ou non confirmée | Galet desserré ; vibration ; connecteur ; `TOLERANCE_PERTE_CAPTEUR_S` |
| D6 | Erreur de bus I2C — les deux postes | Nappe, alimentation des MCP, parasites |
| D7 | Un MCP23017 a perdu sa configuration deux fois de suite — les deux postes | Parasites des drivers, découplage, masse |
| D8 | Initialisation : butée non trouvée, ou butée opposée atteinte | Comme D1 ; sens de rotation (`DIR_VERS_HORAIRE`) ; attribution des `CAP_*` |
| D9 | Initialisation : plage mesurée hors tolérance | Butée déplacée ; `PLAGE_NOMINALE_DEG` ; pas perdus |

## 7. Valeurs à confirmer

Toutes sont dans `config.py`, marquées ⚠ :

| Valeur | Comment | Étape |
|---|---|---|
| `BTN_*` | ✓ relevés le 2026-10-28 ; validation : test_2 menu 1 | 2 |
| `CAP_*`, `CAPTEURS_ACTIFS_BAS` | test_3 menu 2 ; test_5 étape 2 | 3, 4, 9 |
| `EV_*` | test_4 | 5, 6 |
| `TEMPS_MANOEUVRE_MANDRIN_S`, `TEMPS_COUPE_S`, `TEMPS_AVANT_COUPE_S`, `TEMPS_APRES_COUPE_S` | test_4 | 7 |
| `DRIVER_PAS_PAR_TOUR`, `DRIVER_DIP_SWITCH` | étiquette du driver | avant 8 |
| `PUL_*`, `DIR_*`, `ENA_*`, `DIR_VERS_HORAIRE` | test_5 étape 1 | 8 |
| `PLAGE_NOMINALE_DEG` | test_5 étape 3 | 10 |
| `SENS_ROTATION_PLUS` | test_5 étape 4 | 11 |
| `VITESSE_RECHERCHE_RAPIDE_DEG_S`, `DUREE_RAMPE_ROTATION_S` | test_6 menus 4 et 5 | 13, 14 |
| `VITESSE_CROISIERE_DEG_S`, `VITESSE_DEMARRAGE_DEG_S`, `VITESSE_RECENTRAGE_DEG_S` | test_6 menu 1, avec branche | 15 |
| `MARGE_DEPASSEMENT_DEG` | ce que le tuyau du mandrin accepte | avant 27 |
