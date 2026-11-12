from datetime import datetime, timedelta

from services.ledger import compute_ledger
from services.money import fmt, parse_amount

T0 = datetime(2026, 1, 1, 12, 0)
D = lambda n: T0 + timedelta(days=n)


def test_parse_amount_accepts_int_and_float():
    assert parse_amount("50") == 5000
    assert parse_amount("75.5") == 7550
    assert parse_amount("1,250.75") == 125075
    assert parse_amount("50 birr") == 5000
    assert parse_amount("10.005") == 1001  # rounds half up


def test_parse_amount_rejects_garbage():
    for bad in ["", "abc", "-5", "0", "0.00", "nan", "inf", "Infinity", "1e5", "5..5", "99999999999999999999"]:
        assert parse_amount(bad) is None, bad


def test_fmt():
    assert fmt(12050) == "120.50" and fmt(12000) == "120" and fmt(123456700) == "1,234,567"


def test_fines_add_up():
    led = compute_ledger([(1, 10000, T0), (2, 5050, T0)], [], D(3))
    assert led.owed == 15050 and led.fined_total == 15050 and led.interest_total == 0


def test_one_percent_per_week_not_compound():
    f = [(1, 10000, T0)]
    assert compute_ledger(f, [], D(6)).owed == 10000
    assert compute_ledger(f, [], D(7)).owed == 10100
    assert compute_ledger(f, [], D(13)).owed == 10100
    assert compute_ledger(f, [], D(14)).owed == 10200      # 1% of 100, not of 101
    assert compute_ledger(f, [], D(70)).owed == 11000


def test_payment_subtracts_interest_first_then_principal():
    led = compute_ledger([(1, 10000, T0)], [(5000, D(8))], D(8))
    # owed 101, paid 50 -> 51 left (1 interest + 50 paid on principal: 100-49=51 principal)
    assert led.owed == 5100 and led.paid_total == 5000
    assert led.lines[0].interest_due == 0 and led.lines[0].principal_left == 5100


def test_interest_after_partial_payment_uses_remaining_principal():
    led = compute_ledger([(1, 10000, T0)], [(5000, D(8))], D(14))
    assert led.owed == 5100 + 51  # week 2: 1% of 51.00


def test_full_payment_marks_paid_and_stops_interest():
    led = compute_ledger([(1, 10000, T0)], [(10100, D(7))], D(100))
    assert led.owed == 0 and led.lines[0].is_paid and led.next_interest_at is None


def test_payment_applies_to_oldest_fine_first():
    led = compute_ledger([(1, 1000, T0), (2, 2000, T0)], [(1500, D(1))], D(1))
    assert led.lines[0].is_paid and led.lines[1].principal_left == 1500


def test_next_interest_date():
    led = compute_ledger([(1, 10000, T0)], [], D(10))
    assert led.next_interest_at == D(14)


def test_rounding_half_up():
    assert compute_ledger([(1, 5050, T0)], [], D(7)).interest_total == 51  # 50.5 -> 51
