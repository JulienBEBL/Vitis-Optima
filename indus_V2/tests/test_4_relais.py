# -*- coding: utf-8 -*-
"""
test_4_relais.py — Correspondance relais ↔ EV, sens de sortie AIR, chronométrage.

⚠ CE TEST ACTIONNE LES VÉRINS. Air comprimé branché, mains hors des lames.

    python3 tests/test_4_relais.py

Menu :
  1  bascule EV BRIDAGE mère      3  bascule EV BRIDAGE fille
  2  bascule EV COUPE   mère      4  bascule EV COUPE   fille
  c  séquence de coupe complète mère (temporisations de config.py)
  f  séquence de coupe complète fille
  0  tous les relais à 0
  q  quitter (tous les relais à 0)

À vérifier :
  - chaque touche fait réagir LE BON vérin (sinon échanger les EV_* dans config.py) ;
  - bit à 0 : débridé / lame haute ; bit à 1 : bridé / lame basse
    (sinon c'est le raccordement pneumatique AIR 1 / AIR 2 qu'il faut inverser) ;
  - chronométrer la course du vérin de bridage → TEMPS_MANOEUVRE_BRIDAGE_S ;
  - régler TEMPS_COUPE_S pour une coupe franche, et TEMPS_APRES_COUPE_S pour
    que la lame soit remontée avant la fin de la séquence.
"""

import time

import _commun
from _commun import cfg, titre
from libs.materiel import PORT_A

EV = {
    "1": ("EV BRIDAGE mère", cfg.EV_BRIDAGE_MERE),
    "2": ("EV COUPE   mère", cfg.EV_COUPE_MERE),
    "3": ("EV BRIDAGE fille", cfg.EV_BRIDAGE_FILLE),
    "4": ("EV COUPE   fille", cfg.EV_COUPE_FILLE),
}


def afficher(relais) -> None:
    octet = relais.image(PORT_A)
    etats = "   ".join(f"{nom.split()[1]}.{nom.split()[-1]}={'1' if octet & (1 << bit) else '0'}"
                       for nom, bit in EV.values())
    print(f"  [{time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d}]  {etats}")


def sequence_coupe(relais, bit: int) -> None:
    octet = relais.image(PORT_A)
    print(f"  attente {cfg.TEMPS_AVANT_COUPE_S:.2f} s…")
    time.sleep(cfg.TEMPS_AVANT_COUPE_S)
    relais.ecrire_port(PORT_A, octet | (1 << bit))
    afficher(relais)
    time.sleep(cfg.TEMPS_COUPE_S)
    relais.ecrire_port(PORT_A, octet & ~(1 << bit))
    afficher(relais)
    print(f"  attente {cfg.TEMPS_APRES_COUPE_S:.2f} s…")
    time.sleep(cfg.TEMPS_APRES_COUPE_S)
    print("  séquence terminée")


titre("TEST 4 — RELAIS ET ÉLECTROVANNES")
print("  ⚠ Les vérins vont bouger. Mains hors des lames.")
for touche, (nom, bit) in EV.items():
    print(f"    {touche}  bascule {nom}   (0x24 GPA{bit})")
print("    c  coupe complète mère     f  coupe complète fille")
print("    0  tout à 0                q  quitter")

materiel = _commun.ouvrir(avec_gpio=False)
relais = materiel.relais
try:
    afficher(relais)
    while True:
        choix = input("\n  > ").strip().lower()
        if choix == "q":
            break
        if choix in EV:
            _, bit = EV[choix]
            relais.ecrire_port(PORT_A, relais.image(PORT_A) ^ (1 << bit))
        elif choix == "c":
            sequence_coupe(relais, cfg.EV_COUPE_MERE)
        elif choix == "f":
            sequence_coupe(relais, cfg.EV_COUPE_FILLE)
        elif choix == "0":
            relais.ecrire_port(PORT_A, 0x00)
        else:
            print("  touche inconnue")
            continue
        afficher(relais)
except KeyboardInterrupt:
    print()
finally:
    materiel.fermer()
    print("  Tous les relais à 0.\n")
