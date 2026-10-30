# -*- coding: utf-8 -*-
"""
_commun.py — Outils partagés par les scripts de test. Ce n'est pas un test.

Les tests utilisent le VRAI code de libs/ (Materiel, Entrees, Axe) : ils
valident donc à la fois le câblage et le code d'accès au matériel.
Chaque script remet tout en sécurité en sortant (relais à 0, moteurs libres),
y compris sur Ctrl+C.
"""

import logging
import signal
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

import config as cfg                                      # noqa: E402
from libs.materiel import Materiel                         # noqa: E402

logging.basicConfig(level=logging.INFO, format="  · %(message)s")


def _fenetre_fermee(_sig, _frame) -> None:
    """Fenêtre de Geany fermée : comme Ctrl+C, le `finally` du test remet en sécurité."""
    raise KeyboardInterrupt


if hasattr(signal, "SIGHUP"):
    signal.signal(signal.SIGHUP, _fenetre_fermee)


def titre(texte: str) -> None:
    print()
    print("=" * 64)
    print(f"  {texte}")
    print("=" * 64)


def ouvrir(avec_gpio: bool = False) -> Materiel:
    """Vérifie config.py puis ouvre le matériel en état sûr. Quitte en cas d'échec."""
    try:
        cfg.verifier_config()
    except ValueError as erreur:
        print(f"\n  ERREUR DE CONFIGURATION : {erreur}\n")
        sys.exit(2)
    materiel = Materiel()
    try:
        materiel.ouvrir(avec_gpio=avec_gpio)
    except (OSError, RuntimeError) as erreur:
        print(f"\n  ERREUR : {erreur}")
        print("  → lancer d'abord test_1_i2c.py ; diagnostic : sudo i2cdetect -y 1\n")
        materiel.fermer()
        sys.exit(1)
    return materiel


class _LectureSeule:
    """Les deux MCP d'entrée, ouverts SANS toucher à une seule sortie."""

    def __init__(self, bus, relais, entrees):
        self.bus, self.relais, self.entrees = bus, relais, entrees

    def fermer(self) -> None:
        self.bus.fermer()


def ouvrir_lecture_seule() -> _LectureSeule:
    """Pour les tests d'entrées : ne configure QUE les ports d'entrée (direction
    et pull-ups). Aucun relais, aucun ENA, aucun GPIO n'est écrit, ni à
    l'ouverture ni à la fermeture."""
    from libs.materiel import BusI2C, Mcp23017
    try:
        cfg.verifier_config()
        bus = BusI2C(cfg.I2C_BUS_ID)
        # IODIR = 0x00/0x01, GPPU = 0x0C/0x0D. 0x24 : port B seulement.
        bus.ecrire(cfg.MCP_RELAIS_ADDR, 0x01, 0xFF)
        bus.ecrire(cfg.MCP_RELAIS_ADDR, 0x0D, 0xFF)
        for registre in (0x00, 0x01, 0x0C, 0x0D):
            bus.ecrire(cfg.MCP_ENTREES_ADDR, registre, 0xFF)
    except (ValueError, OSError) as erreur:
        print(f"\n  ERREUR : {erreur}\n  → lancer d'abord test_1_i2c.py\n")
        sys.exit(1)
    relais = Mcp23017(bus, cfg.MCP_RELAIS_ADDR, cfg.MCP_RELAIS_IODIR, cfg.MCP_RELAIS_GPPU, (0, 0))
    entrees = Mcp23017(bus, cfg.MCP_ENTREES_ADDR, cfg.MCP_ENTREES_IODIR, cfg.MCP_ENTREES_GPPU, (0, 0))
    return _LectureSeule(bus, relais, entrees)


def bits(octet: int) -> str:
    """Octet en binaire, bit 7 à gauche : « 7654 3210 »."""
    b = f"{octet:08b}"
    return f"{b[:4]} {b[4:]}"


def voyant(actif: bool) -> str:
    return "██" if actif else "··"


def question(texte: str) -> str:
    return input(f"\n  {texte} ").strip().lower()


def confirmer(texte: str) -> bool:
    return question(f"{texte} [o/n]") == "o"


def attendre_entree(texte: str = "Entrée pour continuer, Ctrl+C pour quitter.") -> None:
    input(f"\n  {texte}")


class CompteursMuets:
    """Remplace libs.journal.Compteurs : les essais ne comptent pas dans etat/compteurs.json."""

    def bouton(self, *_, **__):
        pass

    def actionneur(self, *_, **__):
        pass

    def defaut(self, *_, **__):
        pass

    def sauver(self):
        pass

    def sauver_si_du(self, *_, **__):
        pass


def construire_postes(materiel, noms=None) -> tuple:
    """Le VRAI code des postes (libs/poste.py), sans machine.py : pour les tests
    de mouvement. Les relais ne sont pas
    pilotés (mandrins ouverts, lames hautes). Renvoie (entrees, {nom: Poste}, buzzer)."""
    from libs.entrees import Entrees
    from libs.materiel import Buzzer
    from libs.moteur import Axe, PortsDrivers
    from libs.poste import Poste
    drivers = PortsDrivers(materiel.drivers)
    entrees = Entrees(materiel.relais, materiel.entrees)
    buzzer = Buzzer(materiel.puce)
    broches = {cfg.POSTE_MERE: (cfg.PUL_MERE, cfg.DIR_MERE, cfg.ENA_MERE),
               cfg.POSTE_FILLE: (cfg.PUL_FILLE, cfg.DIR_FILLE, cfg.ENA_FILLE)}
    postes = {}
    for nom in (noms or cfg.POSTES):
        axe = Axe(nom, materiel.puce, *broches[nom], drivers)
        postes[nom] = Poste(nom, axe, entrees, CompteursMuets(), buzzer)
    return entrees, postes, buzzer


def tourner(entrees, postes: dict, condition, delai_s: float, quoi: str, buzzer=None) -> float:
    """Boucle à FREQUENCE_BOUCLE_HZ, comme main.py, jusqu'à `condition()`.

    Lève libs.poste.Defaut comme le programme, et TimeoutError au-delà de
    `delai_s`. Renvoie la durée.
    """
    debut = time.monotonic()
    prochain = debut
    while True:
        maintenant = time.monotonic()
        entrees.rafraichir(maintenant)
        for poste in postes.values():
            poste.avancer(maintenant)
        if buzzer is not None:
            buzzer.avancer(maintenant)
        if condition():
            return maintenant - debut
        if maintenant - debut > delai_s:
            raise TimeoutError(f"{quoi} : pas terminé après {delai_s:.0f} s")
        prochain += cfg.PERIODE_BOUCLE_S
        reste = prochain - time.monotonic()
        if reste > 0:
            time.sleep(reste)
        else:
            prochain = time.monotonic()


def initialiser(entrees, postes: dict, buzzer=None, delai_s: float = 150.0) -> float:
    """Initialisation réelle (deux butées en deux passes, puis centrage) des postes donnés.

    Un poste déjà initialisé est d'abord remis en attente : sinon ACQUITTEMENT
    ne ferait qu'un recentrage."""
    from libs.poste import ATTENTE_ACQUITTEMENT, PRET
    maintenant = time.monotonic()
    entrees.rafraichir(maintenant)
    for _ in range(12):                     # remplir l'anti-rebond des butées
        entrees.rafraichir(time.monotonic())
        time.sleep(cfg.PERIODE_BOUCLE_S)
    for poste in postes.values():
        if poste.etat != ATTENTE_ACQUITTEMENT:
            poste.neutraliser(ATTENTE_ACQUITTEMENT)
            poste.axe.attendre_fin(cfg.ARRET_THREAD_MAX_S)
        poste.acquitter(time.monotonic())
    return tourner(entrees, postes, lambda: all(p.etat == PRET for p in postes.values()),
                   delai_s, "initialisation", buzzer)


def arreter_postes(postes: dict, liberer: bool = True) -> None:
    """Arrêt des postes d'un test : moteurs arrêtés, puis libres seulement si
    `liberer` (fin du test). En cours de test, les moteurs restent EXCITÉS : une
    remise sous tension recale le rotor sur un pas entier et décale la position."""
    for poste in postes.values():
        poste.neutraliser()
    for poste in postes.values():
        poste.axe.attendre_fin(cfg.ARRET_THREAD_MAX_S)
        if liberer:
            try:
                poste.axe.liberer()
            except OSError:
                pass


def fichier_resultat(prefixe: str):
    """Chemin logs/<prefixe>_<date>_<heure>.txt : les résultats y sont gardés même
    si la fenêtre se ferme (dans Geany, Ctrl+C la ferme)."""
    from pathlib import Path
    return Path(cfg.CHEMIN_JOURNAL).parent / f"{prefixe}_{time.strftime('%Y%m%d_%H%M%S')}.txt"


def enregistrer(chemin, lignes: list) -> None:
    """(Ré)écrit le fichier de résultat. Une erreur d'écriture n'arrête pas le test."""
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    except OSError as erreur:
        print(f"  (résultat non enregistré : {erreur})")


def menu(texte: str, choix: dict, defaut: str) -> str:
    """Menu au clavier (les scripts sont lancés depuis Geany, sans option en ligne
    de commande). `choix` : touche → libellé. Entrée seule = `defaut`."""
    print(f"\n  {texte}")
    for touche, libelle in choix.items():
        print(f"    {touche} = {libelle}{'   (par défaut)' if touche == defaut else ''}")
    while True:
        reponse = input("  > ").strip().lower() or defaut
        if reponse in choix:
            return reponse
        print("    choix inconnu : " + ", ".join(choix))


def choisir_postes(texte: str = "Poste(s) à tester ?") -> tuple:
    """m, f ou les deux. Renvoie le tuple des noms de postes."""
    reponse = menu(texte, {"m": "mère", "f": "fille", "2": "les deux"}, "2")
    return {"m": (cfg.POSTE_MERE,), "f": (cfg.POSTE_FILLE,)}.get(reponse, cfg.POSTES)


def nombre(texte: str, defaut: int) -> int:
    reponse = input(f"\n  {texte} [{defaut}] ? ").strip()
    return int(reponse) if reponse.isdigit() and int(reponse) > 0 else defaut


SEGMENT_RECHERCHE_DEG = 45.0    # recherche de butée : on demande avant chaque nouveau segment


def chercher_butee(tourner_segment, sens: str) -> tuple:
    """Rotation par segments de SEGMENT_RECHERCHE_DEG jusqu'à une butée.

    La plage réelle peut dépasser la plage nominale de config.py : au lieu
    d'une borne fixe, on DEMANDE à l'opérateur avant chaque nouveau segment
    (le mandrin n'a pas de joint tournant : c'est lui qui voit le tuyau).
    `tourner_segment(pas)` → (pas faits, butée vue ou None, pas à la détection).
    Renvoie (butée vue ou None, pas comptés jusqu'à la détection ou au dernier pas).
    """
    segment = round(SEGMENT_RECHERCHE_DEG * cfg.PAS_PAR_DEGRE)
    total = 0
    while True:
        faits, vue, detection = tourner_segment(segment)
        if vue is not None:
            return vue, total + detection
        total += faits
        print(f" pas de butée après {total / cfg.PAS_PAR_DEGRE:.0f}°")
        if not confirmer(f"Le mandrin peut-il tourner encore de {SEGMENT_RECHERCHE_DEG:.0f}° vers {sens} "
                         "(tuyau compris) ?"):
            return None, total
        print(f"    → {sens}, suite…", end="", flush=True)


def controler_course(poste: str, compte_pas: int, noter, corriger) -> None:
    """Après un trajet butée à butée : compare la course comptée à la course réelle
    vue par l'opérateur (détecte un micropas réglé différemment de config.py),
    puis adopte la course comptée comme plage nominale si elle s'en écarte.
    `corriger(ligne)` ajoute une ligne « à recopier dans config.py »."""
    compte = compte_pas / cfg.PAS_PAR_DEGRE
    texte = input(f"\n  Course comptée butée à butée : {compte:.0f}°. Course RÉELLE vue sur la machine, en "
                  "degrés (Entrée = elle correspond) ? ").strip().replace(",", ".")
    try:
        reel = float(texte) if texte else None
    except ValueError:
        reel = None
    if reel:
        rapport = compte / reel
        if abs(rapport - 1) > 0.15:
            noter(f"  ⚠ {poste} : course comptée {compte:.0f}° pour {reel:.0f}° réels (×{rapport:.2f}). Le "
                  f"driver fait sans doute {cfg.DRIVER_PAS_PAR_TOUR * rapport:.0f} pas/tr au lieu de "
                  f"{cfg.DRIVER_PAS_PAR_TOUR} : vérifier SW5..SW8. Les degrés affichés sont faux d'autant.")
            return
        noter(f"  ✓ {poste} : course comptée {compte:.0f}° ≈ course réelle {reel:.0f}° : micropas conforme")
    nominale = cfg.PLAGE_NOMINALE_DEG[poste]
    if abs(compte - nominale) > 0.1 * nominale:
        noter(f"  ⚠ {poste} : plage ≈ {compte:.0f}°, loin de la plage nominale {nominale:.0f}° de config.py "
              "— adoptée pour la suite du test")
        cfg.PLAGE_NOMINALE_DEG[poste] = round(compte, 1)
        cfg.PLAGE_NOMINALE_PAS[poste] = compte_pas
        cfg.BUDGET_RECHERCHE_RAPIDE_PAS[poste] = compte_pas + cfg.MARGE_DEPASSEMENT_PAS
        corriger(f"PLAGE_NOMINALE_DEG = {{POSTE_MERE: {cfg.PLAGE_NOMINALE_DEG[cfg.POSTE_MERE]}, "
                 f"POSTE_FILLE: {cfg.PLAGE_NOMINALE_DEG[cfg.POSTE_FILLE]}}}   (provisoire, affinée à l'étape suivante)")


# ═══════════════════════════════════════════════════════════════════════════
#  RÉGLAGES MOTEUR MODIFIABLES PENDANT UN TEST  (test_6, test_9)
# ═══════════════════════════════════════════════════════════════════════════

# clé de menu → (libellé, constante en degrés ou secondes, constante calculée ou None)
REGLAGES_MOTEUR = {
    "1": ("vitesse de croisière (°/s)", "VITESSE_CROISIERE_DEG_S", "VITESSE_CROISIERE_SPS"),
    "2": ("vitesse de démarrage (°/s)", "VITESSE_DEMARRAGE_DEG_S", "VITESSE_DEMARRAGE_SPS"),
    "3": ("durée des rampes (s)", "DUREE_RAMPE_ROTATION_S", None),
    "4": ("vitesse passe rapide d'init (°/s)", "VITESSE_RECHERCHE_RAPIDE_DEG_S", "VITESSE_RECHERCHE_RAPIDE_SPS"),
    "5": ("vitesse de recentrage (°/s)", "VITESSE_RECENTRAGE_DEG_S", "VITESSE_RECENTRAGE_SPS"),
    "6": ("zone d'approche des butées (°)", "ZONE_APPROCHE_BUTEE_DEG", "ZONE_APPROCHE_BUTEE_PAS"),
    "7": ("vitesse d'approche des butées (°/s)", "VITESSE_APPROCHE_BUTEE_DEG_S", "VITESSE_APPROCHE_BUTEE_SPS"),
}
ORIGINE_REGLAGES = {constante: getattr(cfg, constante) for _, constante, _ in REGLAGES_MOTEUR.values()}


def appliquer_reglage(constante: str, valeur: float) -> None:
    """Change un réglage pour la suite du test (config.py n'est pas modifié)."""
    from libs import moteur
    for _, deg, calculee in REGLAGES_MOTEUR.values():
        if deg == constante:
            setattr(cfg, deg, valeur)
            if calculee:
                en_pas = valeur * cfg.PAS_PAR_DEGRE
                setattr(cfg, calculee, round(en_pas) if calculee.endswith("_PAS") else en_pas)
    moteur.vider_cache()                        # les rampes calculées dépendent des réglages


def afficher_reglages() -> None:
    print("\n  Réglages actuels :")
    for cle, (libelle, constante, _) in REGLAGES_MOTEUR.items():
        print(f"    {cle}  {libelle:36s} {getattr(cfg, constante)}")


def modifier_reglage() -> str | None:
    """Menu : choisir un réglage et sa nouvelle valeur. Renvoie la ligne « CONSTANTE = valeur »
    appliquée, ou None si rien n'a changé."""
    cle = menu("Quel réglage ?", {c: libelle for c, (libelle, _, _) in REGLAGES_MOTEUR.items()}, "1")
    libelle, constante, _ = REGLAGES_MOTEUR[cle]
    texte = input(f"  Nouvelle valeur pour {libelle} [{getattr(cfg, constante)}] ? ").strip()
    try:
        valeur = float(texte.replace(",", ".")) if texte else getattr(cfg, constante)
    except ValueError:
        print("    valeur invalide")
        return None
    if valeur <= 0:
        print("    refusé : doit être > 0")
        return None
    if constante == "VITESSE_DEMARRAGE_DEG_S" and valeur >= cfg.VITESSE_CROISIERE_DEG_S:
        print("    refusé : la vitesse de démarrage doit rester < la croisière")
        return None
    if constante == "VITESSE_APPROCHE_BUTEE_DEG_S" and valeur > cfg.VITESSE_CROISIERE_DEG_S:
        print("    refusé : la vitesse d'approche doit rester <= la croisière")
        return None
    appliquer_reglage(constante, valeur)
    return f"{constante} = {valeur}"


def lignes_reglages() -> list:
    """Lignes « à recopier dans config.py » : tous les réglages, avec l'ancienne valeur si changée."""
    lignes = ["À recopier dans config.py :"]
    for _, constante, _ in REGLAGES_MOTEUR.values():
        valeur = getattr(cfg, constante)
        ancienne = ORIGINE_REGLAGES[constante]
        lignes.append(f"  {constante} = {valeur}" + ("" if valeur == ancienne else f"   (était {ancienne})"))
    return lignes
