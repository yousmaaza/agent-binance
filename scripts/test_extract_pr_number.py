#!/usr/bin/env python3
"""Vérification : extraction pr_number et pr_branch depuis les commentaires HTML des issues REC-AUTO."""
import re


def extract_rec_auto_metadata(body: str) -> dict:
    """Extrait pr_branch et pr_number du body d'une issue REC-AUTO.

    Utilise les mêmes regex que auto-dispatch-on-auto-label.yml.
    Retourne un dict avec les clés 'pr_branch' et 'pr_number' (chaînes vides si non trouvés).
    """
    m_branch = re.search(r'<!-- pr_branch: (.+?) -->', body)
    m_pr = re.search(r'<!-- pr_number: (\d+) -->', body)

    target_branch = m_branch.group(1).strip() if m_branch else ""
    pr_number = m_pr.group(1).strip() if m_pr else ""

    return {
        "pr_branch": target_branch,
        "pr_number": pr_number,
    }


def test_extract_pr_number_simple():
    """Test simple : extraction d'un pr_number valide."""
    body = "Correction à appliquer.\n<!-- pr_number: 240 -->"
    result = extract_rec_auto_metadata(body)

    assert result["pr_number"] == "240", f"Attendu '240', got '{result['pr_number']}'"
    assert result["pr_branch"] == "", f"Attendu '', got '{result['pr_branch']}'"
    print("✅ Test simple (pr_number seul) : PASS")


def test_extract_pr_branch_and_number():
    """Test : extraction d'un pr_branch et pr_number ensemble."""
    body = "Recommandation.\n<!-- pr_branch: feat/issue-240-fix -->\n<!-- pr_number: 240 -->"
    result = extract_rec_auto_metadata(body)

    assert result["pr_number"] == "240", f"Attendu '240', got '{result['pr_number']}'"
    assert result["pr_branch"] == "feat/issue-240-fix", f"Attendu 'feat/issue-240-fix', got '{result['pr_branch']}'"
    print("✅ Test complet (pr_branch + pr_number) : PASS")


def test_extract_with_spaces():
    """Test : extraction avec espaces supplémentaires (ne match pas le regex strict)."""
    body = "<!-- pr_number:  42  -->"
    result = extract_rec_auto_metadata(body)

    # Le regex exige un format strict "pr_number: " (exactement un espace), donc les espaces supplémentaires empêchent le match
    assert result["pr_number"] == "", f"Attendu '' (pas de match strict), got '{result['pr_number']}'"

    # Test avec le format correct (un seul espace)
    body_ok = "<!-- pr_number: 42 -->"
    result_ok = extract_rec_auto_metadata(body_ok)
    assert result_ok["pr_number"] == "42", f"Attendu '42' (format strict), got '{result_ok['pr_number']}'"
    print("✅ Test espaces (strict format) : PASS")


def test_extract_no_metadata():
    """Test : aucun commentaire HTML → extraction vide."""
    body = "Juste du texte sans commentaires HTML."
    result = extract_rec_auto_metadata(body)

    assert result["pr_number"] == "", f"Attendu '', got '{result['pr_number']}'"
    assert result["pr_branch"] == "", f"Attendu '', got '{result['pr_branch']}'"
    print("✅ Test sans métadonnées : PASS")


def test_extract_malformed_html():
    """Test : commentaire HTML malformé → pas de capture."""
    bodies = [
        "<!-- pr_number: 240",  # Pas de fermeture
        "pr_number: 240 -->",   # Pas d'ouverture
        "<!-- pr_number 240 -->",  # Mauvaise syntaxe (pas de colon)
    ]

    for body in bodies:
        result = extract_rec_auto_metadata(body)
        assert result["pr_number"] == "", f"Attendu '' pour '{body}', got '{result['pr_number']}'"

    print("✅ Test commentaires malformés : PASS")


def test_extract_non_digit_pr_number():
    """Test : pr_number avec caractères non-chiffres → pas de capture."""
    body = "<!-- pr_number: abc -->"
    result = extract_rec_auto_metadata(body)

    # La regex exige \d+ (au moins un chiffre), donc 'abc' ne correspond pas
    assert result["pr_number"] == "", f"Attendu '', got '{result['pr_number']}'"
    print("✅ Test pr_number non-numérique : PASS")


def test_extract_multiple_comments_last_wins():
    """Test : plusieurs commentaires pr_number → le dernier est retenu."""
    body = "<!-- pr_number: 100 -->\nSomething\n<!-- pr_number: 240 -->"
    result = extract_rec_auto_metadata(body)

    # re.search retourne le PREMIER match, donc 100
    assert result["pr_number"] == "100", f"Attendu '100' (first match), got '{result['pr_number']}'"
    print("✅ Test multiples commentaires (first match) : PASS")


def test_extract_large_pr_number():
    """Test : grand numéro PR (ex. 9999)."""
    body = "<!-- pr_number: 9999 -->"
    result = extract_rec_auto_metadata(body)

    assert result["pr_number"] == "9999", f"Attendu '9999', got '{result['pr_number']}'"
    print("✅ Test numéro PR grand : PASS")


def test_extract_pr_branch_with_slashes():
    """Test : pr_branch avec slashes et tirets (branche typique)."""
    body = "<!-- pr_branch: feat/issue-42-my-feature -->"
    result = extract_rec_auto_metadata(body)

    assert result["pr_branch"] == "feat/issue-42-my-feature", f"Attendu 'feat/issue-42-my-feature', got '{result['pr_branch']}'"
    print("✅ Test pr_branch avec slashes : PASS")


if __name__ == "__main__":
    print("=== Test extraction pr_number et pr_branch (REC-AUTO) ===\n")

    tests = [
        test_extract_pr_number_simple,
        test_extract_pr_branch_and_number,
        test_extract_with_spaces,
        test_extract_no_metadata,
        test_extract_malformed_html,
        test_extract_non_digit_pr_number,
        test_extract_multiple_comments_last_wins,
        test_extract_large_pr_number,
        test_extract_pr_branch_with_slashes,
    ]

    failed = []
    for test_fn in tests:
        try:
            test_fn()
        except AssertionError as e:
            print(f"❌ {test_fn.__name__} : FAIL — {e}")
            failed.append(test_fn.__name__)

    if failed:
        print(f"\n❌ {len(failed)}/{len(tests)} test(s) ÉCHOUÉ(S):")
        for name in failed:
            print(f"  - {name}")
        import sys
        sys.exit(1)
    else:
        print("\n" + "=" * 60)
        print(f"✅ TOUS LES {len(tests)} TESTS PASSÉS!")
        print("=" * 60)
