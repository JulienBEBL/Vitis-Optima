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

Faire les étapes dans l'ordre. Ne passer à la suivante que si la précédente est bonne.
Chaque script remet tout en sécurité en sortant, y compris sur `Ctrl+C`. Dans le terminal de
Geany, `Ctrl+C` ferme la fenêtre et le résultat est perdu : les scripts s'arrêtent donc seuls
(test_2, test_3 et la phase 3 de test_5 après un temps sans activité).
Arrêt d'urgence à portée de main dès l'étape 4.3. Mandrins vides jusqu'au § 4.4.

### 4.1 Entrées — rien ne bouge

| # | Commande | À vérifier | Si c'est faux |
|---|---|---|---|
| 1 | `python3 tests/test_1_i2c.py` | 3 × « ✓ » et 3 × « configuration conforme » | câblage I2C, `i2cdetect -y 1` |
| 2 | `python3 tests/test_2_boutons.py` | Programme guidé : il nomme les 9 boutons un par un, tu appuies puis relâches ; résultat (entrée, contact NO / NF) et lignes `BTN_*` à la fin, enregistrés dans `logs/boutons_*.txt` | recopier les `BTN_*` et `BOUTONS_ACTIFS_BAS` proposés |
| 3 | `python3 tests/test_2_boutons.py --apercu` | Chaque bouton allume **son** voyant ; un appui maintenu compte **un** appui ; arrêt seul après 20 s sans appui | — |
| 4 | `python3 tests/test_3_capteurs.py --attribution` | Les 4 butées, HORAIRE / ANTIHORAIRE **vues du côté opérateur** ; contact NO | recopier les `CAP_*` proposés |
| 5 | `python3 tests/test_3_capteurs.py`, galet actionné, **débrancher le connecteur** | Le voyant **s'éteint** (repli sûr) | câblage NF au lieu de NO |

### 4.2 Sorties — les vérins bougent

Air comprimé branché, mains hors des lames et des mandrins.

| # | Commande | À vérifier | Si c'est faux |
|---|---|---|---|
| 6 | `python3 tests/test_4_relais.py` | Chaque relais fait bouger **le bon** organe | recopier les `EV_*` proposés |
| 7 | idem | Relais à 1 = mandrin **fermé** / lame **basse** | croiser AIR 1 / AIR 2 |
| 8 | idem, essai libre, chronomètre | Durée de fermeture du mandrin ; coupe franche | `TEMPS_MANOEUVRE_MANDRIN_S`, `TEMPS_COUPE_S`, `TEMPS_APRES_COUPE_S` |

### 4.3 Moteurs — mandrins vides

Avant tout : **régler et vérifier les DIP des drivers** (6400 pas/tr, 4,28 A RMS, demi-courant
à l'arrêt : `DRIVER_DIP_SWITCH` dans config.py).

| # | Commande | À vérifier | Si c'est faux |
|---|---|---|---|
| 9 | `python3 tests/test_5_moteur.py`, poste mère, phase 1 | **Le moteur mère** tourne (pas la fille) ; dire le sens observé | `DIR_MERE`, `ENA_MERE`, `PUL_MERE` |
| 10 | phase 2 | `DIR_VERS_HORAIRE` proposé ; butée HORAIRE atteinte en tournant horaire | corriger `DIR_VERS_HORAIRE`, ou échanger les `CAP_*` |
| 11 | phase 3, boutons ROTATION ± | Départ doux, croisière, **arrêt net au relâchement**, arrêt sur butée ; ROTATION + dans le sens voulu | `VITESSE_*`, `DUREE_RAMPE_ROTATION_S`, `SENS_ROTATION_PLUS` |
| 12 | idem, poste fille | idem | idem avec `*_FILLE` |
| 13 | `python3 tests/test_6_course.py`, chaque poste | Plage mesurée stable d'une mesure à l'autre ; écart rapide / lente faible | reporter `PLAGE_NOMINALE_DEG` |
| 14 | `python3 tests/test_7_rodage.py` | Les deux moteurs ensemble ; écart de recalage de quelques centièmes de degré ; retard max < 2 ms | courant, rampe, `VITESSE_RECHERCHE_RAPIDE_DEG_S` |

### 4.4 Cycle complet

| # | Action | Attendu |
|---|---|---|
| 15 | `python3 tests/test_8_cycle.py`, sans branche | Cycles complets des deux postes ensemble, sans défaut ni refus inattendu |
| 16 | `python3 main.py`, démarrage | Relais à 0, rien ne bouge. Un appui sur un bouton d'un poste → bip long (I1). |
| 17 | ACQUITTEMENT | Les deux postes s'initialisent ensemble ; double bip chacun |
| 18 | COUPE, mandrin ouvert | Refusée (I3) — sur ce poste seulement |
| 19 | BRIDAGE, puis ROTATION + tenu, relâché | Mandrin fermé ; le mandrin tourne, s'arrête net |
| 20 | ROTATION tenu jusqu'à la butée, puis encore ROTATION dans le même sens | Arrêt sur la butée, bip court ; puis refusé (I4) ; le sens opposé repart |
| 21 | COUPE pendant une rotation, ROTATION pendant une coupe | Refusés (I2) |
| 22 | ROTATION mère et fille en même temps | Les deux tournent |
| 23 | ACQUITTEMENT, mandrin fermé | Le mandrin s'ouvre, puis revient au centre |
| 24 | `Ctrl+C` pendant une rotation | Le moteur s'arrête, relais à 0, moteurs libres |

### 4.5 Cas de défaut — `python3 main.py`

Pour chacun : bip très long ; relais du poste à 0 ; son moteur libre ; ligne `DÉFAUT Dx [poste]`
dans le journal ; **l'autre poste continue** ; ACQUITTEMENT relance l'initialisation du poste.

| # | Provoquer | Attendu |
|---|---|---|
| 25 | Débrancher une butée, puis tourner vers elle en tenant ROTATION | **D1** : le mandrin dépasse la position de la butée d'au plus `MARGE_DEPASSEMENT_DEG`. ⚠ Vérifier d'abord que le tuyau l'accepte. |
| 26 | Couper la puissance d'un driver, puis tourner en partant d'une butée | **D4** en moins de `DEGAGEMENT_MAX_DEG` |
| 27 | Mandrin arrêté sur une butée, débrancher cette butée | **D5** |
| 28 | Shunter les deux butées d'un poste | **D2** |
| 29 | Débrancher une butée, puis ACQUITTEMENT | **D8**. ⚠ Le mandrin peut parcourir jusqu'à la plage + la marge (≈ 140°) avant l'arrêt. |

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
| `BTN_*` | test_2 --attribution | 2 |
| `CAP_*`, `CAPTEURS_ACTIFS_BAS` | test_3 --attribution | 4, 5 |
| `EV_*` | test_4 | 6, 7 |
| `TEMPS_MANOEUVRE_MANDRIN_S`, `TEMPS_COUPE_S`, `TEMPS_AVANT_COUPE_S`, `TEMPS_APRES_COUPE_S` | test_4 | 8 |
| `DRIVER_PAS_PAR_TOUR`, `DRIVER_DIP_SWITCH` | étiquette du driver | avant 9 |
| `DIR_VERS_HORAIRE`, `SENS_ROTATION_PLUS` | test_5 | 9–12 |
| `VITESSE_CROISIERE_DEG_S`, `VITESSE_DEMARRAGE_DEG_S`, `DUREE_RAMPE_ROTATION_S` | test_5 phase 3, avec branche | 11 |
| `PLAGE_NOMINALE_DEG` | test_6 | 13 |
| `VITESSE_RECHERCHE_RAPIDE_DEG_S`, `VITESSE_RECHERCHE_LENTE_DEG_S` | test_6, test_7 | 13, 14 |
| `MARGE_DEPASSEMENT_DEG` | ce que le tuyau du mandrin accepte | avant 25 |
