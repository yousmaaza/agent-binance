"""Cohérence des chemins d'échange entre les scripts de phase et leurs prompts (#403).

Chaque script de `binance-bot/core/phases/*.py` lit et/ou écrit un fichier d'échange dont le
chemin est en dur des deux côtés : `{CYCLE_ID}` côté script (f-string), `__CYCLE_ID__` côté
prompt (substitué à l'exécution par webhook_server.py). Rien ne garantit que ces deux mondes
restent synchronisés — trois incidents constatés le 2026-08-22 (PR #391, PR #397, bug #385)
viennent tous d'une désynchronisation de ce type, rattrapée en review manuelle uniquement.

Côté script, les chemins sont extraits en parcourant l'AST (module `ast`, stdlib) plutôt qu'en
grattant le texte brut : une simple regex ne distingue pas un chemin littéral (`f"/tmp/cycle_..."`)
d'un chemin reconstruit via `os.path.join(PROJECT_DIR, "state", f"cycle_...")`, qui est pourtant
tout aussi comparable statiquement (PROJECT_DIR et les littéraux sont connus). `_resolve_literal`
résout récursivement ce type d'expression (f-string, `PROJECT_DIR`, `os.path.join`, concaténation
`+` de littéraux).

**La charge de la preuve est inversée** : dès qu'un script référence, dans une expression non
entièrement résoluble (`tempfile.gettempdir()`, `tempfile.mkstemp()`, concaténation avec un appel
dynamique...), le nom d'un fichier d'échange que le prompt associé référence *aussi*, le test
échoue — sauf si la ligne porte explicitement le marqueur `# contract-dynamic`. L'absence de
preuve ne vaut jamais preuve de conformité, et l'exemption est à la ligne, pas au fichier :
`phase1_scan.py:121` est aujourd'hui la seule ligne marquée (#414). Un chemin non résoluble qui
ne correspond à AUCUN nom référencé côté prompt n'est pas signalé : il n'est pas partagé, donc
hors du contrat (cf. les scripts de Phase 0 et `phase6_next_cycle.py`, dont certaines sorties ne
sont jamais relues par le prompt — repéré et documenté dans la PR, hors scope de ce ticket).

Côté prompt (texte, pas du Python), l'extraction reste une regex sur le texte brut.

Volontairement hors périmètre : les fichiers d'état persistants (state/trade_history.json,
state/cycle_log.jsonl, state/tp_watcher_state.json, state/maker_pending_orders.json, ...) ne
sont pas des fichiers d'échange éphémères et ne suivent pas le motif cycle_..._phaseN_*.json.
"""
import ast
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

# Noms résolus statiquement quand ils apparaissent comme argument de os.path.join(...) —
# PROJECT_DIR est une constante connue du projet (cf. CLAUDE.md règle #2), pas un chemin dynamique.
KNOWN_LITERAL_NAMES = {"PROJECT_DIR": "PROJECT_DIR"}

# Marqueur à poser sur la ligne d'un chemin d'échange réellement non résoluble statiquement
# (tempfile.mkstemp()/gettempdir()) pour documenter l'exception — cf. phase1_scan.py (#414).
DYNAMIC_MARKER = "# contract-dynamic"

# cycle_<CYCLE_ID>_phaseN_(input|output).json — {CYCLE_ID} après résolution côté script.
EXCHANGE_FILENAME_RE = re.compile(r"cycle_\{CYCLE_ID\}_phase\d+_\w+\.json")

# Motif brut sur le texte des prompts (__CYCLE_ID__, notation substituée à l'exécution),
# avec préfixe de répertoire littéral éventuel.
EXCHANGE_PROMPT_RE = re.compile(r"[\w./]*cycle___CYCLE_ID___phase\d+_\w+\.json")


def _normalize(path: str) -> str:
    """Notation prompt (__CYCLE_ID__) -> notation script ({CYCLE_ID})."""
    return path.replace("__CYCLE_ID__", "{CYCLE_ID}")


def _extract_prompt_paths(prompt_text: str) -> set:
    return {_normalize(m) for m in EXCHANGE_PROMPT_RE.findall(prompt_text)}


def _is_os_path_join_call(node) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "path"
        and isinstance(node.func.value.value, ast.Name)
        and node.func.value.value.id == "os"
    )


def _posix_join(parts: list) -> str:
    result = parts[0]
    for part in parts[1:]:
        if part.startswith("/"):
            result = part
        elif result.endswith("/"):
            result += part
        else:
            result += "/" + part
    return result


def _resolve_literal(node):
    """Résout récursivement une expression AST en chaîne littérale, ou None si impossible.

    Gère : chaîne/f-string littérale, nom PROJECT_DIR, os.path.join(...) et concaténation `+`
    dont TOUS les opérandes sont eux-mêmes résolubles (récursion). Un appel non reconnu
    (tempfile.mkstemp(), tempfile.gettempdir(), variable arbitraire...) fait échouer la
    résolution -> None : c'est ce None qui déclenche la recherche de motif « touché mais non
    résolu » dans _find_exchange_basenames, pas une approbation implicite.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            elif isinstance(value, ast.FormattedValue):
                try:
                    parts.append("{" + ast.unparse(value.value) + "}")
                except Exception:
                    return None
            else:
                return None
        return "".join(parts)
    if isinstance(node, ast.Name) and node.id in KNOWN_LITERAL_NAMES:
        return KNOWN_LITERAL_NAMES[node.id]
    if _is_os_path_join_call(node):
        parts = [_resolve_literal(arg) for arg in node.args]
        if not parts or any(p is None for p in parts):
            return None
        return _posix_join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _resolve_literal(node.left)
        right = _resolve_literal(node.right)
        if left is not None and right is not None:
            return left + right
        return None
    return None


def _is_open_call(node) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open"


def _open_call_path_node(node):
    if node.args:
        return node.args[0]
    for kw in node.keywords:
        if kw.arg == "file":
            return kw.value
    return None


def _find_exchange_basenames(node) -> set:
    """Parcourt tout le sous-arbre AST de `node` (même s'il n'est pas résoluble dans son
    ensemble, ex. `tempfile.gettempdir() + f"/cycle_..."`) et retourne les noms de fichiers
    d'échange qui apparaissent littéralement quelque part dedans, résolus fragment par
    fragment. C'est ce qui permet de détecter qu'une expression "touche" un chemin d'échange
    même quand elle n'est pas résoluble en un chemin complet."""
    found = set()
    for sub in ast.walk(node):
        if isinstance(sub, (ast.Constant, ast.JoinedStr)):
            resolved = _resolve_literal(sub)
            if resolved is not None:
                found.update(EXCHANGE_FILENAME_RE.findall(resolved))
    return found


def _check_node(value_node, lineno, source_lines, script_name, script_paths, unresolved_candidates):
    resolved = _resolve_literal(value_node)
    if resolved is not None:
        basename = resolved.rsplit("/", 1)[-1]
        if EXCHANGE_FILENAME_RE.fullmatch(basename):
            script_paths.add(resolved)
        return

    basenames = _find_exchange_basenames(value_node)
    if not basenames:
        return

    line_text = source_lines[lineno - 1] if 0 <= lineno - 1 < len(source_lines) else ""
    for basename in basenames:
        unresolved_candidates.append(
            {"basename": basename, "lineno": lineno, "line_text": line_text, "script_name": script_name}
        )


def _extract_script_paths(script_name, script_text):
    """Retourne (script_paths, unresolved_candidates) pour un script de phase.

    - script_paths : chemins littéraux complets, résolus statiquement.
    - unresolved_candidates : expressions non résolubles qui touchent pourtant un nom de fichier
      d'échange (basename, lineno, line_text, script_name) — statut (divergence/documenté/hors
      contrat) tranché plus loin dans find_divergences, une fois les chemins du prompt connus.
    """
    tree = ast.parse(script_text)
    source_lines = script_text.splitlines()
    script_paths = set()
    unresolved_candidates = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            _check_node(node.value, node.lineno, source_lines, script_name, script_paths, unresolved_candidates)
        elif _is_open_call(node):
            path_node = _open_call_path_node(node)
            if path_node is not None:
                _check_node(path_node, node.lineno, source_lines, script_name, script_paths, unresolved_candidates)

    return script_paths, unresolved_candidates


def find_divergences(script_name, script_text, prompt_name, prompt_text):
    """Compare les chemins d'échange partagés entre un script et son prompt.

    Retourne (divergences, dynamic_notes) :
    - divergences : chemin littéral qui diffère entre les deux mondes, OU expression non
      résoluble statiquement qui touche un nom de fichier d'échange référencé aussi par le
      prompt, sans marqueur `# contract-dynamic` sur sa ligne (charge de la preuve inversée :
      l'absence de résolution ne vaut jamais approbation implicite).
    - dynamic_notes : chemins dynamiques rencontrés mais explicitement documentés (informationnel).
    """
    script_paths, unresolved_candidates = _extract_script_paths(script_name, script_text)
    prompt_paths = _extract_prompt_paths(prompt_text)

    script_by_name = {p.rsplit("/", 1)[-1]: p for p in script_paths}
    prompt_by_name = {p.rsplit("/", 1)[-1]: p for p in prompt_paths}

    divergences = []
    dynamic_notes = []

    for candidate in unresolved_candidates:
        basename = candidate["basename"]
        if basename not in prompt_by_name:
            # Chemin non partagé (ex. sortie de Phase 0 jamais relue par le prompt) : pas de
            # contrat à vérifier ici, cf. docstring du module.
            continue
        if DYNAMIC_MARKER in candidate["line_text"]:
            dynamic_notes.append(f"{candidate['script_name']}:{candidate['lineno']} (marqueur {DYNAMIC_MARKER!r} présent)")
            continue
        divergences.append(
            f"{candidate['script_name']}:{candidate['lineno']} référence le chemin d'échange partagé "
            f"'{basename}' (attendu par {prompt_name}) dans une expression non résoluble "
            f"statiquement en chemin complet, sans le marqueur {DYNAMIC_MARKER!r} sur la ligne — "
            f"vérifier manuellement la cohérence avec {prompt_name} puis ajouter le marqueur si "
            f"c'est intentionnel."
        )

    shared_names = set(script_by_name) & set(prompt_by_name)
    for name in sorted(shared_names):
        script_path = script_by_name[name]
        prompt_path = prompt_by_name[name]
        if script_path != prompt_path:
            divergences.append(
                f"Chemin d'échange divergent pour '{name}' entre {script_name} et {prompt_name} :\n"
                f"  script : {script_path}\n"
                f"  prompt : {prompt_path}"
            )

    return divergences, dynamic_notes


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

    def test_diverging_literal_fstring_path_is_detected(self):
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

    def test_diverging_os_path_join_regression_is_detected(self):
        """Forme rejouée lors de la première review de la PR #423 : os.path.join(PROJECT_DIR,
        "state", f"...") remplaçant un f"/tmp/..." littéral — passait inaperçue avec la liste
        blanche par fichier de la toute première version du test."""
        script_text = (
            'in_path = os.path.join(PROJECT_DIR, "state", f"cycle_{CYCLE_ID}_phase5_input.json")\n'
        )
        prompt_text = "Construis /tmp/cycle___CYCLE_ID___phase5_input.json avec les ordres.\n"

        divergences, _ = find_divergences(
            "phase5_execution.py", script_text, "phase5_execution.txt", prompt_text
        )

        self.assertEqual(len(divergences), 1)
        message = divergences[0]
        self.assertIn("phase5_execution.py", message)
        self.assertIn("phase5_execution.txt", message)
        self.assertIn("PROJECT_DIR/state/cycle_{CYCLE_ID}_phase5_input.json", message)
        self.assertIn("/tmp/cycle_{CYCLE_ID}_phase5_input.json", message)

    def test_diverging_string_concat_with_gettempdir_is_detected(self):
        """Forme rejouée lors de la deuxième review de la PR #423 : tempfile.gettempdir() +
        f"/cycle_..." sur un chemin partagé (phase7_mongo.py / phases6_8.txt) — passait inaperçue
        car seul os.path.join(...) déclenchait la vérification "touche un motif mais non résolu"
        dans la version précédente. La charge de la preuve doit s'appliquer à toute expression
        non résoluble, pas seulement à os.path.join(...)."""
        script_text = (
            'in_path = tempfile.gettempdir() + f"/cycle_{CYCLE_ID}_phase7_input.json"\n'
        )
        prompt_text = "Écris d'abord le document dans /tmp/cycle___CYCLE_ID___phase7_input.json.\n"

        divergences, _ = find_divergences(
            "phase7_mongo.py", script_text, "phases6_8.txt", prompt_text
        )

        self.assertEqual(len(divergences), 1)
        message = divergences[0]
        self.assertIn("phase7_mongo.py", message)
        self.assertIn("phases6_8.txt", message)
        self.assertIn("cycle_{CYCLE_ID}_phase7_input.json", message)
        self.assertIn(DYNAMIC_MARKER, message)

    def test_matching_literal_path_has_no_divergence(self):
        script_text = 'out_path = f"/tmp/cycle_{CYCLE_ID}_phase5_output.json"\n'
        prompt_text = "Le script écrit /tmp/cycle___CYCLE_ID___phase5_output.json.\n"

        divergences, _ = find_divergences(
            "phase5_execution.py", script_text, "phase5_execution.txt", prompt_text
        )

        self.assertEqual(divergences, [])


class TestDetectsUnregisteredDynamicPath(unittest.TestCase):
    """Un chemin construit dynamiquement (tempfile.mkstemp/gettempdir, concaténation...) et non
    marqué `# contract-dynamic` sur sa ligne doit faire échouer le test dès lors que le nom de
    fichier est référencé aussi par le prompt — plutôt que d'être ignoré silencieusement
    (cf. PR #414 : c'est ce qui rend un chemin non comparable statiquement). L'exemption est à
    la ligne, pas au fichier : une autre ligne du même script reste vérifiée. Un chemin non
    résoluble mais NON partagé avec le prompt n'est en revanche pas signalé (pas de faux positif
    sur les sorties de Phase 0 jamais relues, hors périmètre du contrat)."""

    def test_unmarked_dynamic_path_fails(self):
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
        self.assertIn(DYNAMIC_MARKER, divergences[0])

    def test_unmarked_dynamic_path_not_shared_with_prompt_is_ignored(self):
        """Un chemin non résoluble qui ne correspond à aucun nom référencé côté prompt n'est
        pas un chemin du contrat (ex. sortie de Phase 0 jamais relue) : pas de faux positif."""
        script_text = (
            "out_path = os.path.join(tempfile.gettempdir(), "
            'f"cycle_{CYCLE_ID}_phase9_output.json")\n'
        )
        prompt_text = "Ce prompt ne référence aucun chemin d'échange de la phase 9.\n"

        divergences, dynamic_notes = find_divergences(
            "phase9_hypothetical.py", script_text, "phase9_hypothetical.txt", prompt_text
        )

        self.assertEqual(divergences, [])
        self.assertEqual(dynamic_notes, [])

    def test_marked_dynamic_path_does_not_fail(self):
        script_text = (
            "out_path = os.path.join(tempfile.gettempdir(), "
            'f"cycle_{CYCLE_ID}_phase1_output.json")  # contract-dynamic: voir #414\n'
        )
        prompt_text = "Le script écrit /tmp/cycle___CYCLE_ID___phase1_output.json.\n"

        divergences, dynamic_notes = find_divergences(
            "phase1_scan.py", script_text, "phase1_scan.txt", prompt_text
        )

        self.assertEqual(divergences, [])
        self.assertEqual(len(dynamic_notes), 1)

    def test_marker_exemption_is_per_line_not_per_file(self):
        """Une deuxième ligne non marquée dans le même fichier doit continuer à être vérifiée,
        même si une première ligne porte le marqueur (exemption à la ligne, pas au fichier)."""
        script_text = (
            "marked_path = os.path.join(tempfile.gettempdir(), "
            'f"cycle_{CYCLE_ID}_phase1_output.json")  # contract-dynamic: voir #414\n'
            "unmarked_path = os.path.join(tempfile.gettempdir(), "
            'f"cycle_{CYCLE_ID}_phase9_output.json")\n'
        )
        prompt_text = (
            "/tmp/cycle___CYCLE_ID___phase1_output.json\n"
            "/tmp/cycle___CYCLE_ID___phase9_output.json\n"
        )

        divergences, dynamic_notes = find_divergences(
            "phase1_scan.py", script_text, "phase1_scan.txt", prompt_text
        )

        self.assertEqual(len(divergences), 1)
        self.assertIn("phase1_scan.py", divergences[0])
        self.assertIn(DYNAMIC_MARKER, divergences[0])
        self.assertEqual(len(dynamic_notes), 1)


if __name__ == "__main__":
    unittest.main()
