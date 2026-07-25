"""Harness partagé pour les tests d'intégration des scripts de phase.

Regroupe les patterns communs à tests/test_phase0_*.py et tests/test_phase1_scan.py :
- interception de state/trade_history.json en mémoire (sans jamais toucher au vrai fichier)
- écriture/nettoyage du scénario JSON consommé par tests/fixtures/fake_kraken.py
- exécution d'un script de phase top-level via importlib, avec sys.argv et cleanup garantis

Les fichiers de test restent responsables de leur propre pile de patches (core.trade_helpers.tg,
_save_trade_history_atomic, _load_config, log_phase0_event...) car elle diffère d'un script de
phase à l'autre — ce module ne factorise que ce qui est réellement identique partout.
"""
import builtins
import importlib.util
import io
import json
import os
import sys
import tempfile
import uuid

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FAKE_KRAKEN_PATH = os.path.join(PROJECT_DIR, "tests", "fixtures", "fake_kraken.py")
TRADE_HISTORY_PATH = os.path.join(PROJECT_DIR, "state", "trade_history.json")

_real_open = builtins.open


def new_cycle_id() -> str:
    return f"test_{uuid.uuid4().hex[:12]}"


def fake_open_factory(history_text):
    """Intercepte uniquement la lecture de trade_history.json — le reste passe par le vrai open()."""
    def _fake_open(path, mode="r", *args, **kwargs):
        if os.path.abspath(str(path)) == TRADE_HISTORY_PATH and "r" in mode:
            return io.StringIO(history_text)
        return _real_open(path, mode, *args, **kwargs)
    return _fake_open


def write_kraken_scenario(scenario_data: dict) -> str:
    """Écrit le scénario JSON pour fake_kraken.py dans un fichier temporaire, retourne son chemin.

    Contrairement aux fichiers input/output des scripts de phase (chemins /tmp hardcodés par les
    scripts eux-mêmes, non modifiables ici), ce chemin est entièrement choisi par le test —
    tempfile est donc utilisable sans contrainte.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(scenario_data or {}, f)
        return f.name


def set_fake_kraken_env(scenario_path: str) -> str | None:
    """Positionne FAKE_KRAKEN_SCENARIO, retourne l'ancienne valeur pour restauration ultérieure."""
    old_env = os.environ.get("FAKE_KRAKEN_SCENARIO")
    os.environ["FAKE_KRAKEN_SCENARIO"] = scenario_path
    return old_env


def restore_fake_kraken_env(old_env: str | None) -> None:
    if old_env is None:
        os.environ.pop("FAKE_KRAKEN_SCENARIO", None)
    else:
        os.environ["FAKE_KRAKEN_SCENARIO"] = old_env


def load_and_remove_json(path: str):
    """Lit un JSON puis supprime le fichier. Retourne None si le fichier n'existe pas
    (cas d'un script qui sort avant d'écrire sa sortie, ex. erreur de parsing en amont)."""
    if not os.path.exists(path):
        return None
    with open(path) as f:
        data = json.load(f)
    os.remove(path)
    return data


def remove_if_exists(*paths: str) -> None:
    for p in paths:
        if os.path.exists(p):
            os.remove(p)


def exec_phase_script(script_path: str, cycle_id: str):
    """Charge et exécute un script de phase top-level via importlib.

    Positionne sys.argv = [nom_script, cycle_id] pendant l'exécution puis le restaure.
    Retourne exit_code (None si le script ne fait pas sys.exit(), sinon le code passé).
    """
    old_argv = sys.argv
    script_name = os.path.basename(script_path)
    sys.argv = [script_name, cycle_id]
    exit_code = None
    try:
        spec = importlib.util.spec_from_file_location(f"{script_name}_{cycle_id}", script_path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except SystemExit as e:
            exit_code = e.code
    finally:
        sys.argv = old_argv
    return exit_code
