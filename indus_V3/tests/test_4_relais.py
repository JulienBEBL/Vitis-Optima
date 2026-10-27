# -*- coding: utf-8 -*-
"""
test_4_relais.py — Qui est qui : quel relais pilote quelle électrovanne.

⚠ CE TEST ACTIONNE LES MANDRINS ET LES LAMES. Air comprimé branché, mains
   hors des lames et des mandrins. Les moteurs ne bougent pas.

    python3 tests/test_4_relais.py

IDENTIFICATION (automatique, tu observes et tu réponds)
  Le script essaie l'un après l'autre les 6 relais du PCB (0x24 GPA2 à GPA7) :
  il en active UN pendant DUREE_ACTIVATION_S, puis le relâche. Tu regardes ce
  qui a bougé sur la machine et tu réponds :
      1 = MANDRIN mère               3 = MANDRIN fille
      2 = COUPE mère                 4 = COUPE fille
      0 = rien n'a bougé             r = recommencer ce relais
  À la fin : les lignes EV_* à recopier dans config.py (ou à m'envoyer).

  Il te demande aussi le SENS : relais activé, le mandrin doit se FERMER et la
  lame DESCENDRE. Si c'est l'inverse, ce n'est pas le programme qu'il faut
  changer mais le raccordement pneumatique (sorties AIR 1 / AIR 2), pour que
  « relais à 0 » reste l'état sûr : mandrin ouvert, lame haute.

ESSAI LIBRE (ensuite, si tu veux)
  Avec la correspondance trouvée : 1 2 3 4 = bascule, c / f = séquence de coupe
  complète mère / fille aux temporisations de config.py, 0 = tout à 0, q = quitter.
  Sert à chronométrer : TEMPS_MANOEUVRE_MANDRIN_S, TEMPS_COUPE_S, TEMPS_APRES_COUPE_S.
"""

import time

import _commun
from _commun import cfg, confirmer, titre
from libs.materiel import PORT_A

DUREE_ACTIVATION_S = 1.0
BITS_RELAIS = range(2, 8)        # les 6 relais du PCB : 0x24 GPA2..GPA7

FONCTIONS = {
    "1": ("EV_MANDRIN_MERE", "MANDRIN mère", "le mandrin s'est-il FERMÉ"),
    "2": ("EV_COUPE_MERE", "COUPE mère", "la lame est-elle DESCENDUE"),
    "3": ("EV_MANDRIN_FILLE", "MANDRIN fille", "le mandrin s'est-il FERMÉ"),
    "4": ("EV_COUPE_FILLE", "COUPE fille", "la lame est-elle DESCENDUE"),
}

titre("TEST 4 — RELAIS ET ÉLECTROVANNES : QUI EST QUI")
print("  ⚠ Mandrins et lames vont bouger. Mains hors des lames et des mandrins.")
print(f"  Chaque relais est activé {DUREE_ACTIVATION_S:.1f} s puis relâché.")
print("  Réponses : 1 = mandrin mère   2 = coupe mère   3 = mandrin fille   4 = coupe fille")
print("             0 = rien n'a bougé   r = recommencer ce relais")

materiel = _commun.ouvrir(avec_gpio=False)
relais = materiel.relais


def impulsion(bit: int) -> None:
    relais.ecrire_port(PORT_A, 1 << bit)
    time.sleep(DUREE_ACTIVATION_S)
    relais.ecrire_port(PORT_A, 0x00)


def sequence_coupe(bit: int) -> None:
    base = relais.image(PORT_A)
    time.sleep(cfg.TEMPS_AVANT_COUPE_S)
    debut = time.monotonic()
    relais.ecrire_port(PORT_A, base | (1 << bit))
    time.sleep(cfg.TEMPS_COUPE_S)
    relais.ecrire_port(PORT_A, base & ~(1 << bit))
    time.sleep(cfg.TEMPS_APRES_COUPE_S)
    print(f"    coupe : relais actif {cfg.TEMPS_COUPE_S:.2f} s, puis {cfg.TEMPS_APRES_COUPE_S:.2f} s "
          f"de remontée — séquence terminée en {time.monotonic() - debut + cfg.TEMPS_AVANT_COUPE_S:.2f} s")


try:
    if not confirmer("Zone dégagée, lancer l'identification ?"):
        raise SystemExit("  Non lancé.")

    # ── IDENTIFICATION ─────────────────────────────────────────────────────
    trouve = {}          # constante → bit
    sens_faux = []
    for bit in BITS_RELAIS:
        while True:
            print(f"\n  Relais 0x24 GPA{bit} : activation…", end="", flush=True)
            impulsion(bit)
            reponse = input(" qu'est-ce qui a bougé ? [1 2 3 4 0 r] ").strip().lower()
            if reponse == "r":
                continue
            if reponse == "0":
                print("    → rien sur ce relais")
                break
            if reponse not in FONCTIONS:
                print("    réponse inconnue : 1, 2, 3, 4, 0 ou r")
                continue
            constante, libelle, question_sens = FONCTIONS[reponse]
            if constante in trouve:
                print(f"    ⚠ {libelle} est déjà attribué au GPA{trouve[constante]} — recommence (r) ou réponds 0")
                continue
            trouve[constante] = bit
            if not confirmer(f"  Relais activé, {question_sens} (puis revenue(s) au relâchement) ?"):
                sens_faux.append(libelle)
            print(f"    → {libelle} = GPA{bit}")
            break
        if len(trouve) == len(FONCTIONS):
            break

    # ── RÉSULTAT ───────────────────────────────────────────────────────────
    print("\n  ┌─ RÉSULTAT À RECOPIER DANS config.py (ou à m'envoyer) " + "─" * 20)
    for constante, libelle, _ in FONCTIONS.values():
        actuel = getattr(cfg, constante)
        if constante in trouve:
            marque = "✓ comme config.py" if trouve[constante] == actuel else f"← À CORRIGER (config.py : {actuel})"
            print(f"  │ {constante:18s} = {trouve[constante]}    # 0x24 GPA{trouve[constante]}   {marque}")
        else:
            print(f"  │ {constante:18s} : NON TROUVÉ — {libelle} n'a réagi sur aucun relais")
    for libelle in sens_faux:
        print(f"  │ ⚠ {libelle} : sens inversé → croiser AIR 1 / AIR 2 sur cette EV")
    print("  └" + "─" * 73)

    # ── ESSAI LIBRE ────────────────────────────────────────────────────────
    if len(trouve) == len(FONCTIONS) and confirmer("Passer à l'essai libre (chronométrage) ?"):
        touches = {touche: trouve[constante] for touche, (constante, _, _) in FONCTIONS.items()}
        print("    1 2 3 4 = bascule   c = coupe complète mère   f = coupe complète fille")
        print("    0 = tout à 0        q = quitter")
        while True:
            choix = input("\n  > ").strip().lower()
            if choix == "q":
                break
            if choix in touches:
                relais.ecrire_port(PORT_A, relais.image(PORT_A) ^ (1 << touches[choix]))
            elif choix == "c":
                sequence_coupe(trouve["EV_COUPE_MERE"])
            elif choix == "f":
                sequence_coupe(trouve["EV_COUPE_FILLE"])
            elif choix == "0":
                relais.ecrire_port(PORT_A, 0x00)
            else:
                print("    touche inconnue")
                continue
            octet = relais.image(PORT_A)
            print("    " + "   ".join(f"{FONCTIONS[t][1]} = {'1' if octet & (1 << b) else '0'}"
                                      for t, b in touches.items()))
except KeyboardInterrupt:
    print("\n  Interrompu.")
finally:
    materiel.fermer()
    print("  Tous les relais à 0.\n")
