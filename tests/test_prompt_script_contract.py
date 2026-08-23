"""Cohérence des chemins d'échange entre les scripts de phase et leurs prompts (#403).

Chaque script de `binance-bot/core/phases/*.py` lit et/ou écrit un fichier d'échange dont le
chemin est en dur des deux côtés : `{CYCLE_ID}` côté script (f-string), `__CYCLE_ID__` côté
prompt (substitué à l'exécution par webhook_server.py). Rien ne garantit que ces deux mondes
restent synchronisés — trois incidents constatés le 2026-08-22 (PR #391, PR #397, bug #385)
viennent tous d'une désynchronisation de ce type, rattrapée en review manuelle uniquement.

Ce module extrait par regex les chemins `cycle_..._phaseN_(input|output).json` référencés dans
chaque script et dans le prompt qui l'invoque, puis compare les chemins qui partagent le même
nom de fichier. Un chemin construit dynamiquement (tempfile.mkstemp/gettempdir) n'est pas
comparable littéralement : il doit être explicitement documenté dans KNOWN_DYNAMIC_PATHS, sinon
le test échoue pour le signaler plutôt que de l'ignorer silencieusement (cf. PR #414).

Volontairement hors périmètre : les fichiers d'état persistants (state/trade_history.json,
state/cycle_log.jsonl, state/tp_watcher_state.json, state/maker_pending_orders.json, ...) ne
sont pas des fichiers d'échange éphémères et ne suivent pas le motif cycle_..._phaseN_*.json.
"""
import os
import re
import unittest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHASES_DIR = os.path.join(PROJECT_DIR, "binance-bot", "core", "phases")
PROMPTS_DIR = os.path.join(PROJECT_DIR, "prompts", "phases")

# Script de phase -> prompt qui l'invoque et lui fournit/consomme ses fichiers d'échange.
SCRIPT_TO_PROMPT = {
    "phase0_snapshot.py": "phase0_snapshot.txt",
    "phase0_profit.py": "phase0_snapshot.txt",
    "phase0_oco_retry.py": "phase0_snapshot.txt",
    "phase0_trailing_stop.py": "phase0_snapshot.txt",
    "phase1_scan.py": "phase1_scan.txt",
    "phase3_scoring.py": "phase3_scoring.txt",
    "phase4_sizing.py": "phase4_sizing.txt",
    "phase5_execution.py": "phase5_execution.txt",
    "phase6_next_cycle.py": "phases6_8.txt",
    "phase7_mongo.py": "phases6_8.txt",
    "phase8_cycle_log.py": "phases6_8.txt",
}

# tempfile.mkstemp()/tempfile.gettempdir() empêchent une comparaison littérale du chemin.
# Scripts déjà connus pour construire leur chemin d'échange ainsi, avec la raison :
# - phase1_scan.py : tempfile.gettempdir() sans préfixe littéral dans le code (#414) — fonctionne
#   aujourd'hui car gettempdir() renvoie /tmp sur macOS/Linux, mais dépendance implicite.
# - phase5_execution.py : tempfile.mkstemp() utilisé uniquement pour une écriture atomique, le
#   chemin final (out_path) reste littéral et identique à celui attendu par le prompt (PR #397).
KNOWN_DYNAMIC_PATHS = {"phase1_scan.py", "phase5_execution.py"}

DYNAMIC_MARKERS = ("tempfile.mkstemp(", "tempfile.gettempdir(")

# cycle_<CYCLE_ID>_phaseN_(input|output).json, avec préfixe de répertoire littéral éventuel.
# Côté script : {CYCLE_ID} (f-string) — côté prompt : __CYCLE_ID__ (notation de substitution).
EXCHANGE_PATH_RE = re.compile(r"[\w./]*cycle_(?:\{CYCLE_ID\}|__CYCLE_ID__)_phase\d+_\w+\.json")

# Docstring de module : documentation, pas du code exécuté — ignorée pour éviter les faux
# positifs d'un commentaire obsolète (ex. phase1_scan.py mentionne "$TMPDIR/..." en docstring
# alors que le code réel construit le chemin autrement, cf. KNOWN_DYNAMIC_PATHS ci-dessus).
_MODULE_DOCSTRING_RE = re.compile(r'\A"""(?:.|\n)*?"""', re.MULTILINE)


def _normalize(path: str) -> str:
    """Notation prompt (__CYCLE_ID__) -> notation script ({CYCLE_ID})."""
    return path.replace("__CYCLE_ID__", "{CYCLE_ID}")


def _extract_script_paths(script_text: str) -> set:
    code_only = _MODULE_DOCSTRING_RE.sub("", script_text, count=1)
    return {_normalize(m) for m in EXCHANGE_PATH_RE.findall(code_only)}


def _extract_prompt_paths(prompt_text: str) -> set:
    return {_normalize(m) for m in EXCHANGE_PATH_RE.findall(prompt_text)}


def find_divergences(script_name, script_text, prompt_name, prompt_text):
    """Compare les chemins d'échange partagés entre un script et son prompt.

    Retourne (divergences, dynamic_paths) :
    - divergences : messages d'échec pour un chemin littéral qui diffère entre les deux mondes,
      ou un chemin construit dynamiquement sans être documenté dans KNOWN_DYNAMIC_PATHS.
    - dynamic_paths : chemins dynamiques rencontrés mais déjà documentés (informationnel).
    """
    script_paths = _extract_script_paths(script_text)
    prompt_paths = _extract_prompt_paths(prompt_text)

    script_by_name = {p.rsplit("/", 1)[-1]: p for p in script_paths}
    prompt_by_name = {p.rsplit("/", 1)[-1]: p for p in prompt_paths}
    shared_names = set(script_by_name) & set(prompt_by_name)

    divergences = []
    dynamic_paths = []
    has_dynamic_marker = any(marker in script_text for marker in DYNAMIC_MARKERS)

    for name in sorted(shared_names):
        script_path = script_by_name[name]
        prompt_path = prompt_by_name[name]

        is_dynamic = "/" not in script_path
        if is_dynamic:
            if script_name in KNOWN_DYNAMIC_PATHS:
                dynamic_paths.append(f"{script_name}: {name} (chemin construit dynamiquement, documenté)")
                continue
            divergences.append(
                f"{script_name} construit le chemin d'échange '{name}' dynamiquement "
                f"(pas de répertoire littéral dans le code, marqueurs détectés : {has_dynamic_marker}) "
                f"sans être répertorié dans KNOWN_DYNAMIC_PATHS — vérifier manuellement la cohérence "
                f"avec {prompt_name} puis ajouter au registre si c'est intentionnel."
            )
            continue

        if script_path != prompt_path:
            divergences.append(
                f"Chemin d'échange divergent pour '{name}' entre {script_name} et {prompt_name} :\n"
                f"  script : {script_path}\n"
                f"  prompt : {prompt_path}"
            )

    return divergences, dynamic_paths


class TestExchangePathCoherence(unittest.TestCase):
    """Pour chaque script de phase, les chemins d'échange qu'il partage avec son prompt associé
    doivent être identiques des deux côtés (cf. incidents PR #391 et PR #397)."""

    def test_all_phase_scripts_match_their_prompt(self):
        for script_name, prompt_name in sorted(SCRIPT_TO_PROMPT.items()):
            with self.subTest(script=script_name, prompt=prompt_name):
                script_path = os.path.join(PHASES_DIR, script_name)
                prompt_path = os.path.join(PROMPTS_DIR, prompt_name)
                with open(script_path) as f:
                    script_text = f.read()
                with open(prompt_path) as f:
                    prompt_text = f.read()

                divergences, _ = find_divergences(script_name, script_text, prompt_name, prompt_text)
                self.assertEqual(divergences, [], "\n".join(divergences))


class TestDetectsReintroducedRegression(unittest.TestCase):
    """Reproduit sur des chaînes de caractères la régression de la PR #391 (chemin divergent
    /tmp vs state d'un seul côté) : le test doit échouer en nommant script, prompt et chemins."""

    def test_diverging_literal_path_is_detected(self):
        script_text = 'out_path = f"state/cycle_{CYCLE_ID}_phase5_output.json"\n'
        prompt_text = "Le script écrit /tmp/cycle___CYCLE_ID___phase5_output.json.\n"

        divergences, _ = find_divergences(
            "phase5_execution.py", script_text, "phase5_execution.txt", prompt_text
        )

        self.assertEqual(len(divergences), 1)
        message = divergences[0]
        self.assertIn("phase5_execution.py", message)
        self.assertIn("phase5_execution.txt", message)
        self.assertIn("state/cycle_{CYCLE_ID}_phase5_output.json", message)
        self.assertIn("/tmp/cycle_{CYCLE_ID}_phase5_output.json", message)

    def test_matching_literal_path_has_no_divergence(self):
        script_text = 'out_path = f"/tmp/cycle_{CYCLE_ID}_phase5_output.json"\n'
        prompt_text = "Le script écrit /tmp/cycle___CYCLE_ID___phase5_output.json.\n"

        divergences, _ = find_divergences(
            "phase5_execution.py", script_text, "phase5_execution.txt", prompt_text
        )

        self.assertEqual(divergences, [])


class TestDetectsUnregisteredDynamicPath(unittest.TestCase):
    """Un chemin construit dynamiquement (tempfile.mkstemp/gettempdir) et non documenté dans
    KNOWN_DYNAMIC_PATHS doit faire échouer le test plutôt que d'être ignoré silencieusement
    (cf. PR #414 : c'est ce qui rend un chemin non comparable statiquement)."""

    def test_unregistered_dynamic_path_fails(self):
        script_text = (
            "out_path = os.path.join(tempfile.gettempdir(), "
            'f"cycle_{CYCLE_ID}_phase9_output.json")\n'
        )
        prompt_text = "Le script écrit /tmp/cycle___CYCLE_ID___phase9_output.json.\n"

        divergences, _ = find_divergences(
            "phase9_hypothetical.py", script_text, "phase9_hypothetical.txt", prompt_text
        )

        self.assertEqual(len(divergences), 1)
        self.assertIn("phase9_hypothetical.py", divergences[0])
        self.assertIn("KNOWN_DYNAMIC_PATHS", divergences[0])

    def test_registered_dynamic_path_does_not_fail(self):
        script_text = (
            "out_path = os.path.join(tempfile.gettempdir(), "
            'f"cycle_{CYCLE_ID}_phase1_output.json")\n'
        )
        prompt_text = "Le script écrit /tmp/cycle___CYCLE_ID___phase1_output.json.\n"

        divergences, dynamic_paths = find_divergences(
            "phase1_scan.py", script_text, "phase1_scan.txt", prompt_text
        )

        self.assertEqual(divergences, [])
        self.assertEqual(len(dynamic_paths), 1)


if __name__ == "__main__":
    unittest.main()
