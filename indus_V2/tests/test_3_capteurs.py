# -*- coding: utf-8 -*-
"""
test_3_capteurs.py — Les fins de course : où elles arrivent, dans quel sens.

Lecture seule : aucun relais, aucun ENA n'est écrit. Ctrl+C pour le bilan.

    python3 tests/test_3_capteurs.py

Le script ne suppose RIEN de config.py. Il affiche en direct les 8 bits bruts
de chaque port d'entrée (0x26 A, 0x26 B, 0x24 B) et la liste des bits qui ont
changé depuis le lancement. Actionner un galet à la main, un par un :

  - un bit doit basculer, et son nom apparaître dans « ont bougé » ;
  - noter quel bit pour quel galet → CAP_* dans config.py ;
  - câblage attendu (COM à la masse, contact NO) : le bit vaut 1 galet libre,
    0 galet actionné. Si c'est l'inverse, le contact câblé est le NC.
  - galet actionné, débrancher le connecteur : le bit doit revenir à 1.

Si AUCUN bit ne bouge sur aucun port : le signal n'arrive pas au MCP. Vérifier
que COM est bien relié à la MASSE du PCB (pas au 3,3 V, pas en l'air), que le
fil NO arrive sur une entrée câblée (0x26 : GPA4..GPA7, GPB0..GPB4), et
mesurer au multimètre la continuité COM–NO galet actionné.
"""

import time

import _commun
from _commun import bits, cfg, titre

PORTS = ("0x26 A", "0x26 B", "0x24 B")
ATTENDUS = {("0x26 A", cfg.CAP_MERE_COUPE): "mère coupe",
            ("0x26 A", cfg.CAP_MERE_LIGATURAGE): "mère ligaturage",
            ("0x26 A", cfg.CAP_FILLE_COUPE): "fille coupe",
            ("0x26 A", cfg.CAP_FILLE_LIGATURAGE): "fille ligaturage"}

titre("TEST 3 — FINS DE COURSE (bits bruts)")
materiel = _commun.ouvrir_lecture_seule()


def lire() -> dict:
    a, b = materiel.entrees.lire_ports()
    return {"0x26 A": a, "0x26 B": b, "0x24 B": materiel.relais.lire_port(1)}


try:
    depart = lire()
    bascules = {}                # (port, bit) → nombre de changements
    precedent = dict(depart)
    print("  Bits affichés 7654 3210. Actionner les galets un par un.\n")
    print("  0x26 A      0x26 B      0x24 B      ont bougé")
    while True:
        octets = lire()
        for port in PORTS:
            change = octets[port] ^ precedent[port]
            for bit in range(8):
                if change & (1 << bit):
                    bascules[(port, bit)] = bascules.get((port, bit), 0) + 1
        precedent = octets
        liste = " ".join(f"{port.replace(' ', '')}{bit}" for (port, bit) in sorted(bascules))
        print("\r  " + "   ".join(bits(octets[port]) for port in PORTS) + f"   {liste:40s}",
              end="", flush=True)
        time.sleep(0.02)
except KeyboardInterrupt:
    print("\n\n  Bilan — bits qui ont changé :")
    if not bascules:
        print("    aucun. Le signal n'arrive pas au MCP : voir l'en-tête de ce script.")
    for (port, bit), nombre in sorted(bascules.items()):
        repos = (depart[port] >> bit) & 1
        role = ATTENDUS.get((port, bit), "non prévu dans config.py")
        print(f"    {port} bit {bit} : {nombre} changement(s), valait {repos} au lancement — {role}")
    print("\n  config.py attend actuellement :")
    for (port, bit), role in ATTENDUS.items():
        vu = "✓ a bougé" if (port, bit) in bascules else "✗ n'a pas bougé"
        print(f"    {role:17s} → {port} bit {bit}   {vu}")
    print()
finally:
    materiel.fermer()
