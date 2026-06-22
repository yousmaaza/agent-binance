#!/usr/bin/env python3
"""Vérification : next_1h_slot() sur une semaine UTC — pas de collision avec slots 4h."""
from datetime import datetime, timezone, timedelta


def next_1h_slot_logic(now: datetime) -> datetime:
    """Applique la logique de next_1h_slot() à un temps donné (pour test)."""
    nxt = now.replace(minute=5, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(hours=1)
    if nxt.hour % 4 == 0:
        nxt += timedelta(hours=1)
    return nxt


def test_1h_slot_sequence():
    """Teste la séquence des slots 1h sur une semaine UTC."""
    slots_4h = {0, 4, 8, 12, 16, 20}
    start = datetime(2026, 6, 21, 0, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(days=7)

    print("=== Test séquence slots 1h sur une semaine UTC ===\n")

    all_slots = []
    current = start

    # Collecter tous les slots pour chaque heure de la semaine
    while current < end:
        slot = next_1h_slot_logic(current)
        if not all_slots or slot != all_slots[-1]:
            all_slots.append(slot)
        # Avancer d'une heure
        current += timedelta(hours=1)

    # Vérifications
    errors = []

    # 1. Pas de collision avec slots 4h
    for slot in all_slots:
        if slot.hour in slots_4h:
            errors.append(f"❌ COLLISION: slot à {slot.isoformat()} — heure {slot.hour} est un 4h slot!")

    # 2. Vérifier la séquence (chaque slot est 1h après le précédent, sauf quand on skip un 4h slot)
    for i in range(1, len(all_slots)):
        prev_slot = all_slots[i - 1]
        curr_slot = all_slots[i]
        gap = (curr_slot - prev_slot).total_seconds() / 3600

        # Si l'heure précédente % 4 == 3, le slot suivant saute 4h, donc gap = 2h
        # Sinon, gap = 1h
        expected_gap = 2 if prev_slot.hour % 4 == 3 else 1

        if abs(gap - expected_gap) > 0.01:
            errors.append(
                f"❌ GAP INCORRECT: de {prev_slot.isoformat()} "
                f"à {curr_slot.isoformat()} = {gap}h (attendu {expected_gap}h)"
            )

    # 3. Afficher les résultats
    if errors:
        print(f"Erreurs détectées ({len(errors)}):")
        for err in errors:
            print(f"  {err}")
        return False

    print(f"✅ Séquence valide sur {len(all_slots)} slots\n")
    print("Premiers slots de chaque jour (example):")
    seen_days = set()
    for slot in all_slots:
        day_key = slot.strftime("%Y-%m-%d")
        if day_key not in seen_days:
            print(f"  {slot.isoformat()} ({slot.strftime('%A')})")
            seen_days.add(day_key)

    return True


def test_no_4h_collisions():
    """Teste qu'aucun appel à next_1h_slot() ne retourne un 4h slot."""
    slots_4h_hours = {0, 4, 8, 12, 16, 20}
    print("\n=== Test : pas de collision avec slots 4h (tests ponctuels) ===\n")

    errors = []

    # Tester depuis chaque minute d'une heure, pour différentes heures de la journée
    for hour in range(24):
        for minute in [0, 3, 5, 10, 55, 59]:
            test_time = datetime(2026, 6, 21, hour, minute, 0, tzinfo=timezone.utc)
            slot = next_1h_slot_logic(test_time)

            if slot.hour in slots_4h_hours and slot.minute == 5:
                errors.append(
                    f"❌ ERREUR: De {test_time.isoformat()} → "
                    f"{slot.isoformat()} (4h slot!)"
                )

    if errors:
        print(f"Erreurs détectées ({len(errors)}):")
        for err in errors[:10]:
            print(f"  {err}")
        return False

    print("✅ Aucun appel n'a retourné un 4h slot (24h × 6 tests = 144 cas testés)")
    return True


if __name__ == "__main__":
    success = test_1h_slot_sequence()
    success = test_no_4h_collisions() and success

    if success:
        print("\n" + "=" * 60)
        print("✅ TOUS LES TESTS PASSÉS!")
        print("=" * 60)

    import sys
    sys.exit(0 if success else 1)
