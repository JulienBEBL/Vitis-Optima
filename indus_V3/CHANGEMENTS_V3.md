# Vitis Optima — indus V3 · Changements par rapport à la V2

Point de départ : copie de `indus_V2/` au commit `f529fc0` (2026-10-14).
`indus_V2/` reste intact : c'est la référence qui tourne sur la machine actuelle.

Ce fichier suit, étape par étape, ce qui change entre la V2 et la V3. Une fois une
modification validée et codée, elle est reportée dans `LOGIQUE.md` (la référence) et
`config.py` ; ce fichier garde l'historique et le pourquoi.

Méthode : questions → décisions → `LOGIQUE.md` → `config.py` → code → tests, chaque étape
validée avant la suivante.

---

## 1. Matériel

Relevé auprès de Julien le 2026-10-27. ⚠ = à préciser (questions en § 5).

| Sujet | V2 | V3 | Conséquence sur le code |
|---|---|---|---|
| PCB | « indus V1 » Clean & Protech, MCP 0x24 / 0x25 / 0x26 | **inchangé** | `materiel.py` inchangé |
| Postes | mère + fille, liés par l'ordre maître / esclave | mère + fille, **totalement indépendants** (électrique, mécanique, logique) | plus de coordinateur inter-postes |
| Boutons par poste | 3 : BRIDAGE, COUPE, POSITION | 4 : BRIDAGE, ROTATION +, ROTATION −, COUPE ⚠ câblage des 2 nouveaux | 8 boutons + ACQUITTEMENT |
| Lames / EV | 4 EV (bridage × 2, coupe × 2) | 2 lames en moins ⚠ liste exacte des EV restantes | mapping relais à refaire |
| Mandrin | — | **nouveau** : mandrin pneumatique piloté par une EV, serre la branche, tourne avec le moteur, **sans joint tournant** pneumatique | la rotation doit rester dans la plage |
| Mécanique de l'axe | moteur entre 2 positions (coupe / ligaturage) | moteur à arbre **parallèle au sol**, sur un **guide de translation déplacé à la main** ; il fait tourner le mandrin | aucune mesure de la translation |
| Fins de course | 2 par axe : POSITION_COUPE / POSITION_LIGATURAGE | 2 par axe, déplacées : **butées MIN / MAX de rotation** du mandrin, plage ≈ 130° ⚠ à mesurer | même câblage, nouveau sens |
| Moteurs | NEMA 34, DM860H | **NEMA 24** (à confirmer), pas de réducteur ⚠ driver et réglages | courant, vitesses, rampes à reprendre |
| Capteurs ajoutés | — | **aucun** | — |

## 2. Logique

| Sujet | V2 | V3 | Conséquence sur le code |
|---|---|---|---|
| Cycle | bridage → coupe → POSITION maître puis esclave → ouverture des 2 pinces → ACQUITTEMENT | **par poste, indépendant** : bridage (mandrin fermé) → déplacement manuel du bloc pour positionner la branche → rotation libre à la demande dans la plage → coupe → recul manuel du bloc → bridage (mandrin ouvert) | machine à états du poste réécrite |
| Maître / esclave | fille maître, I7, retard sens aller | **supprimé** | I7, I9, `MOTEUR_MAITRE`, `RETARD_SENS_ALLER_S` supprimés |
| Enchaînement | aucun automatisme | **aucun automatisme** : l'opérateur choisit chaque action | — |
| Sécurité coupe | coupe en position coupe seulement (I4) | coupe **interdite si le mandrin du poste est ouvert** ; poste par poste (mandrin fille ouvert ⇒ coupe fille interdite, la mère n'est pas concernée) | nouvel interlock |
| Rotation | mouvement d'un capteur à l'autre | rotation **commandée par l'opérateur**, bornée par les 2 capteurs MIN / MAX | nouveau mode de mouvement |
| Démarrage | ACQUITTEMENT → référencement esclave puis maître en position coupe | **recherche lente sur les 2 moteurs, puis recentrage propre** ⚠ détails | référencement réécrit |
| Défauts | globaux, sortie par ACQUITTEMENT | principe gardé, ajustements selon les essais ⚠ portée par poste ? | à revoir avec l'indépendance |
| Sens inversé | proposition d'un défaut « fin de course opposée = sens inversé » | **refusé** : 100 % manuel, confiance à l'opérateur | rien à coder |

## 3. Décisions

| Date | Décision |
|---|---|
| 2026-10-27 | Partir d'une copie de la V2 plutôt que d'une page blanche. |
| 2026-10-27 | PCB et 3 MCP inchangés. Aucun capteur ajouté. Pas de réducteur. |
| 2026-10-27 | Plus de maître / esclave : deux postes totalement indépendants. |
| 2026-10-27 | Aucun enchaînement automatique d'actions. |
| 2026-10-27 | Pas de défaut « sens inversé ». |
| 2026-10-27 | La machine est démontée pour la V3 : la V2 deviendra obsolète. |

## 4. Avancement

- [x] 2026-10-27 — dossier `indus_V3/` créé (copie de la V2, comportement inchangé)
- [x] 2026-10-27 — premières réponses de Julien consignées (§ 1 à 3)
- [ ] Questions de suivi (§ 5) et décisions
- [ ] `LOGIQUE.md` mis à jour et validé
- [ ] `config.py` mis à jour et validé
- [ ] Code (`main.py`, `libs/`)
- [ ] Scripts de test (`tests/`)
- [ ] Essais machine

---

## 5. Questions ouvertes (2026-10-27)

Posées à Julien, en attente de réponse. Les réponses seront reportées en § 1 à 3.

- **A. EV et relais** — liste exacte des EV de la V3 par poste (mandrin, coupe, autre ?) ;
  le mandrin remplace-t-il le bridage ? relais utilisés ; bit à 0 = mandrin ouvert ou fermé ?
- **B. Boutons** — bits des 2 nouveaux boutons ; ROTATION + / − : maintenu = tourne, ou un pas
  par appui ?
- **C. Rotation** — vitesse, rampes ; arrêt sur capteur seulement ou butées logicielles avant ;
  rotation autorisée mandrin ouvert ? pendant la coupe ? quel capteur est MIN, lequel MAX.
- **D. Démarrage** — sur appui ACQUITTEMENT ou automatique ; capteur recherché ; « recentrer »
  = milieu de la plage mesurée ?
- **E. Retour au centre** — automatique (à l'ouverture du mandrin ?) ou jamais.
- **F. Défauts** — par poste ou globaux ; rôle de l'unique ACQUITTEMENT.
- **G. Moteurs** — référence NEMA 24, driver (toujours DM860H ?), courant, pas/tour, maintien
  en position.
