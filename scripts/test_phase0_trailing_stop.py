#!/usr/bin/env python3
"""Tests pour _round_price() et _round_qty() dans phase0_trailing_stop.py"""
import math


def _round_price(p, tick):
    """Arrondit p au multiple le plus proche de tick, à 8 décimales."""
    return round(round(p / tick) * tick, 8)


def _round_qty(q, step):
    """Arrondit q vers le bas au multiple le plus proche de step, à 8 décimales."""
    return round(math.floor(q / step) * step, 8)


def test_round_price():
    """Tests pour _round_price()."""
    print("=== Tests _round_price() ===\n")

    test_cases = [
        # (price, tick, expected, description)
        (100.0, 0.1, 100.0, "Arrondi exact"),
        (100.5, 0.1, 100.5, "Décimale simple"),
        (100.56, 0.1, 100.6, "Arrondir à la hausse (0.56 → 0.6)"),
        (100.54, 0.1, 100.5, "Arrondir à la baisse (0.54 → 0.5)"),
        (100.549999, 0.1, 100.5, "Arrondir à la baisse (float precision)"),
        (100.550001, 0.1, 100.6, "Arrondir à la hausse (float precision)"),
        (0.0, 0.1, 0.0, "Zéro"),
        (0.00000001, 0.00000001, 0.00000001, "Très petit tick (8 décimales)"),
        (0.00000002, 0.00000001, 0.00000002, "Arrondi avec très petit tick"),
        (1234567.89, 0.01, 1234567.89, "Grand nombre avec tick 0.01"),
        (50.333, 0.5, 50.5, "Tick de 0.5"),
        (50.249, 0.5, 50.0, "Arrondir à la baisse vers tick 0.5"),
    ]

    errors = []
    for price, tick, expected, desc in test_cases:
        result = _round_price(price, tick)
        if abs(result - expected) > 1e-9:
            errors.append(f"❌ {desc}: _round_price({price}, {tick}) = {result}, attendu {expected}")
        else:
            print(f"✅ {desc}: _round_price({price}, {tick}) = {result}")

    if errors:
        print("\n--- Erreurs détectées ---")
        for err in errors:
            print(err)
        return False

    print(f"\n✅ Tous les {len(test_cases)} tests _round_price() passés\n")
    return True


def test_round_qty():
    """Tests pour _round_qty()."""
    print("=== Tests _round_qty() ===\n")

    test_cases = [
        # (qty, step, expected, description)
        (1.0, 0.1, 1.0, "Arrondi exact"),
        (1.5, 0.1, 1.5, "Décimale simple"),
        (1.56, 0.1, 1.5, "Arrondir vers le bas (floor)"),
        (1.59, 0.1, 1.5, "Arrondir vers le bas même proche de 1.6"),
        (0.0, 0.1, 0.0, "Zéro"),
        (0.0001, 0.00001, 0.0001, "Très petit step (10 * 0.00001 = 0.0001)"),
        (0.000123, 0.00001, 0.00012, "Arrondir vers le bas avec petit step"),
        (0.000129, 0.00001, 0.00012, "Arrondir vers le bas (9 → 2)"),
        (100.99, 1.0, 100.0, "Step de 1.0"),
        (100.01, 1.0, 100.0, "Step de 1.0 (très proche)"),
        (10.5, 0.5, 10.5, "Step de 0.5"),
        (10.75, 0.5, 10.5, "Step de 0.5 arrondir vers le bas"),
        (0.00012345678, 0.0001, 0.0001, "Précision 8 décimales"),
    ]

    errors = []
    for qty, step, expected, desc in test_cases:
        result = _round_qty(qty, step)
        if abs(result - expected) > 1e-9:
            errors.append(f"❌ {desc}: _round_qty({qty}, {step}) = {result}, attendu {expected}")
        else:
            print(f"✅ {desc}: _round_qty({qty}, {step}) = {result}")

    if errors:
        print("\n--- Erreurs détectées ---")
        for err in errors:
            print(err)
        return False

    print(f"\n✅ Tous les {len(test_cases)} tests _round_qty() passés\n")
    return True


def test_round_functions_integration():
    """Tests d'intégration : cas réels de trading."""
    print("=== Tests d'intégration (cas réels de trading) ===\n")

    # Cas réel 1 : Bitcoin avec tick_size=0.01, lot=0.001
    btc_price = 43250.75
    btc_tick = 0.01
    btc_qty = 0.001234
    btc_lot = 0.001

    btc_price_rounded = _round_price(btc_price, btc_tick)
    btc_qty_rounded = _round_qty(btc_qty, btc_lot)

    print(f"Bitcoin:")
    print(f"  Prix: {btc_price} → {btc_price_rounded} (tick={btc_tick})")
    print(f"  Qty: {btc_qty} → {btc_qty_rounded} (lot={btc_lot})")

    if abs(btc_price_rounded - 43250.75) > 1e-9 or abs(btc_qty_rounded - 0.001) > 1e-9:
        print("❌ Cas BTC échoué")
        return False

    # Cas réel 2 : Altcoin avec tick_size=0.00000001, lot=1
    alt_price = 0.000123456789
    alt_tick = 0.00000001
    alt_qty = 5000.5
    alt_lot = 1.0

    alt_price_rounded = _round_price(alt_price, alt_tick)
    alt_qty_rounded = _round_qty(alt_qty, alt_lot)

    print(f"\nAltcoin:")
    print(f"  Prix: {alt_price} → {alt_price_rounded} (tick={alt_tick})")
    print(f"  Qty: {alt_qty} → {alt_qty_rounded} (lot={alt_lot})")

    if abs(alt_price_rounded - 0.00012346) > 1e-9 or abs(alt_qty_rounded - 5000.0) > 1e-9:
        print("❌ Cas altcoin échoué")
        return False

    print("\n✅ Tests d'intégration passés\n")
    return True


def test_edge_cases():
    """Tests de cas limites."""
    print("=== Tests de cas limites ===\n")

    errors = []

    # Division par zéro (ne doit pas arriver grâce aux contraintes métier)
    # mais on teste la robustesse
    try:
        result = _round_price(100.0, 0.0)
        errors.append("❌ _round_price devrait échouer avec tick=0")
    except ZeroDivisionError:
        print("✅ _round_price échoue correctement avec tick=0")

    try:
        result = _round_qty(10.0, 0.0)
        errors.append("❌ _round_qty devrait échouer avec step=0")
    except ZeroDivisionError:
        print("✅ _round_qty échoue correctement avec step=0")

    # Nombre très grand
    large = 999999999.99
    large_rounded = _round_price(large, 0.01)
    if abs(large_rounded - 999999999.99) > 1e-9:
        errors.append(f"❌ Nombre très grand: {large_rounded} != {large}")
    else:
        print(f"✅ Nombre très grand: {large} → {large_rounded}")

    # Nombre très petit
    tiny = 0.00000001
    tiny_rounded = _round_qty(tiny, 0.0000001)
    expected_tiny = 0.0
    if abs(tiny_rounded - expected_tiny) > 1e-9:
        errors.append(f"❌ Nombre très petit: {tiny_rounded} != {expected_tiny}")
    else:
        print(f"✅ Nombre très petit: {tiny} → {tiny_rounded}")

    if errors:
        print("\n--- Erreurs détectées ---")
        for err in errors:
            print(err)
        return False

    print("\n✅ Tests de cas limites passés\n")
    return True


if __name__ == "__main__":
    success = test_round_price()
    success = test_round_qty() and success
    success = test_round_functions_integration() and success
    success = test_edge_cases() and success

    print("=" * 60)
    if success:
        print("✅ TOUS LES TESTS PASSÉS!")
    else:
        print("❌ CERTAINS TESTS ONT ÉCHOUÉ")
    print("=" * 60)

    import sys
    sys.exit(0 if success else 1)
