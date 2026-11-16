from datetime import datetime, timedelta
from types import SimpleNamespace

from services import store

T0 = datetime(2026, 1, 1, 12, 0)


def mk(db, tid, name):
    u = store.get_or_create_user(db, SimpleNamespace(id=tid, username=None, full_name=name))
    u.is_authenticated = True
    db.commit()
    return u


def pair(db):
    a, b = mk(db, 1, "Abel"), mk(db, 2, "Bete")
    other, status = store.link_partners(db, b, a.invite_code)
    assert status == "ok" and other.id == a.id
    return a, b


def test_invite_statuses(db):
    a, b = pair(db)
    assert store.link_partners(db, b, a.invite_code)[1] == "already"
    assert store.link_partners(db, a, a.invite_code)[1] == "self"
    assert store.link_partners(db, a, "nope")[1] == "invalid"
    assert [p.id for p in store.partners_of(db, a)] == [b.id]


def test_only_the_other_person_can_answer_a_fine(db):
    a, b = pair(db)
    c = mk(db, 3, "Chala")
    e, _ = store.create_fine(db, a, b, 5000, "late")
    assert store.respond(db, e.id, a, True)[1]          # sender cannot accept own fine
    assert store.respond(db, e.id, c, True)[1]          # stranger cannot
    assert store.respond(db, e.id, b, True, now=T0)[1] is None
    assert store.respond(db, e.id, b, False)[1]         # already answered


def test_cannot_fine_a_stranger(db):
    a, _ = pair(db)
    c = mk(db, 3, "Chala")
    assert store.create_fine(db, a, c, 100, None)[1]


def test_full_cycle_fine_then_payment(db):
    a, b = pair(db)
    f1, _ = store.create_fine(db, a, b, 10000, None)
    f2, _ = store.create_fine(db, a, b, 5000, None)
    store.respond(db, f1.id, b, True, now=T0)
    store.respond(db, f2.id, b, False, now=T0)             # rejected -> not counted
    assert store.owed(db, b, a, T0).owed == 10000
    assert store.owed(db, a, b, T0).owed == 0               # direction matters

    p, err = store.create_payment(db, b, a, 4000, now=T0)
    assert err is None
    assert store.owed(db, b, a, T0).owed == 10000           # pending payment does not count yet
    store.respond(db, p.id, a, True, now=T0)
    assert store.owed(db, b, a, T0).owed == 6000

    p2, _ = store.create_payment(db, b, a, 1000, now=T0)
    store.respond(db, p2.id, a, False, now=T0)               # rejected -> not subtracted
    assert store.owed(db, b, a, T0).owed == 6000


def test_payment_rules(db):
    a, b = pair(db)
    assert store.create_payment(db, b, a, 100, now=T0)[1]    # owes nothing
    f, _ = store.create_fine(db, a, b, 10000, None)
    store.respond(db, f.id, b, True, now=T0)
    assert store.create_payment(db, b, a, 10001, now=T0)[1]  # more than owed
    p, _ = store.create_payment(db, b, a, 10000, now=T0)
    assert store.respond(db, p.id, b, True, now=T0)[1]       # payer cannot confirm own payment
    assert store.respond(db, p.id, a, True, now=T0)[1] is None
    assert store.owed(db, b, a, T0 + timedelta(days=30)).owed == 0


def test_two_pending_payments_cannot_overpay(db):
    a, b = pair(db)
    f, _ = store.create_fine(db, a, b, 10000, None)
    store.respond(db, f.id, b, True, now=T0)
    p1, _ = store.create_payment(db, b, a, 8000, now=T0)
    p2, _ = store.create_payment(db, b, a, 8000, now=T0)
    assert store.respond(db, p1.id, a, True, now=T0)[1] is None
    assert store.respond(db, p2.id, a, True, now=T0)[1]      # now exceeds what is owed


def test_cancel(db):
    a, b = pair(db)
    e, _ = store.create_fine(db, a, b, 100, None)
    assert store.cancel(db, e.id, b)[1]                      # only creator
    assert store.cancel(db, e.id, a)[1] is None
    assert "cancelled" in store.respond(db, e.id, b, True)[1]


def test_both_directions_are_independent(db):
    a, b = pair(db)
    f1, _ = store.create_fine(db, a, b, 10000, None)
    f2, _ = store.create_fine(db, b, a, 3000, None)
    store.respond(db, f1.id, b, True, now=T0)
    store.respond(db, f2.id, a, True, now=T0)
    assert store.owed(db, b, a, T0).owed == 10000
    assert store.owed(db, a, b, T0).owed == 3000
