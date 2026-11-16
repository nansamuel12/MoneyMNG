"""Database operations. All business checks live here."""
import secrets
from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from config import WEEKLY_INTEREST_PERCENT
from models import Entry, Partnership, User, utcnow
from services.ledger import Ledger, compute_ledger
from services.money import fmt


def display_name(u: User) -> str:
    return u.full_name or (f"@{u.username}" if u.username else f"User {u.telegram_id}")


# ---------- users & partners ----------

def _new_code(db: Session) -> str:
    while True:
        code = secrets.token_hex(5)
        if not db.query(User).filter_by(invite_code=code).first():
            return code


def get_or_create_user(db: Session, tg_user) -> User:
    user = db.query(User).filter_by(telegram_id=tg_user.id).first()
    if user is None:
        user = User(
            telegram_id=tg_user.id,
            username=tg_user.username,
            full_name=tg_user.full_name,
            invite_code=_new_code(db),
        )
        db.add(user)
    else:
        user.username = tg_user.username
        user.full_name = tg_user.full_name
    db.commit()
    return user


def are_partners(db: Session, a_id: int, b_id: int) -> bool:
    lo, hi = sorted((a_id, b_id))
    return db.query(Partnership).filter_by(user_a_id=lo, user_b_id=hi).first() is not None


def partners_of(db: Session, user: User) -> list[User]:
    rows = db.query(Partnership).filter(
        or_(Partnership.user_a_id == user.id, Partnership.user_b_id == user.id)
    ).all()
    ids = [r.user_b_id if r.user_a_id == user.id else r.user_a_id for r in rows]
    if not ids:
        return []
    return db.query(User).filter(User.id.in_(ids)).order_by(User.full_name).all()


def link_partners(db: Session, user: User, code: str):
    """Returns (other_user | None, status) with status: ok | already | self | invalid."""
    other = db.query(User).filter_by(invite_code=code).first()
    if other is None or not other.is_authenticated:
        return None, "invalid"
    if other.id == user.id:
        return None, "self"
    if are_partners(db, user.id, other.id):
        return other, "already"
    lo, hi = sorted((user.id, other.id))
    db.add(Partnership(user_a_id=lo, user_b_id=hi))
    db.commit()
    return other, "ok"


# ---------- balance ----------

def owed(db: Session, debtor: User, creditor: User, now: datetime | None = None) -> Ledger:
    """What `debtor` owes `creditor`: accepted fines they gave minus accepted payments."""
    now = now or utcnow()
    fines = db.query(Entry).filter_by(
        kind="fine", status="accepted", creator_id=creditor.id, other_id=debtor.id
    ).all()
    pays = db.query(Entry).filter_by(
        kind="payment", status="accepted", creator_id=debtor.id, other_id=creditor.id
    ).all()
    return compute_ledger(
        [(f.id, f.amount_cents, f.responded_at) for f in fines],
        [(p.amount_cents, p.responded_at) for p in pays],
        now,
        WEEKLY_INTEREST_PERCENT,
    )


# ---------- requests ----------

def create_fine(db: Session, sender: User, other: User, amount_cents: int, note: str | None):
    """Returns (entry, error)."""
    if not are_partners(db, sender.id, other.id):
        return None, "You are not connected with this person."
    e = Entry(kind="fine", creator_id=sender.id, other_id=other.id,
              amount_cents=amount_cents, note=note or None)
    db.add(e)
    db.commit()
    return e, None


def create_payment(db: Session, payer: User, receiver: User, amount_cents: int,
                   now: datetime | None = None):
    """Returns (entry, error). The payer says 'I paid'; the receiver must confirm."""
    if not are_partners(db, payer.id, receiver.id):
        return None, "You are not connected with this person."
    led = owed(db, payer, receiver, now)
    if led.owed <= 0:
        return None, f"You don't owe {display_name(receiver)} anything."
    if amount_cents > led.owed:
        return None, f"You only owe {fmt(led.owed)}. Please enter that or less."
    e = Entry(kind="payment", creator_id=payer.id, other_id=receiver.id,
              amount_cents=amount_cents)
    db.add(e)
    db.commit()
    return e, None


def respond(db: Session, entry_id: int, user: User, accept: bool, now: datetime | None = None):
    """The OTHER person accepts or rejects. Returns (entry, error)."""
    now = now or utcnow()
    e = db.get(Entry, entry_id)
    if e is None or e.other_id != user.id:
        return None, "This request is not for you."
    if e.status == "cancelled":
        return None, "This request was cancelled by the sender."
    if e.status != "pending":
        return None, "This request was already answered."
    if accept and e.kind == "payment":
        # Re-check: balance may have changed since the payment was entered.
        led = owed(db, e.creator, e.other, now)
        if e.amount_cents > led.owed:
            return None, (f"This payment ({fmt(e.amount_cents)}) is more than what is owed now "
                          f"({fmt(led.owed)}). Please reject it and ask for a new one.")
    e.status = "accepted" if accept else "rejected"
    e.responded_at = now
    db.commit()
    return e, None


def cancel(db: Session, entry_id: int, user: User):
    """The creator withdraws a request nobody answered yet. Returns (entry, error)."""
    e = db.get(Entry, entry_id)
    if e is None or e.creator_id != user.id:
        return None, "You can only cancel your own requests."
    if e.status != "pending":
        return None, "This request was already answered."
    e.status = "cancelled"
    e.responded_at = utcnow()
    db.commit()
    return e, None


def pending_for(db: Session, user: User) -> list[Entry]:
    return db.query(Entry).filter_by(other_id=user.id, status="pending").order_by(Entry.created_at).all()


def waiting_on(db: Session, user: User) -> list[Entry]:
    return db.query(Entry).filter_by(creator_id=user.id, status="pending").order_by(Entry.created_at).all()


def history(db: Session, user: User, limit: int = 15) -> list[Entry]:
    return (
        db.query(Entry)
        .filter(or_(Entry.creator_id == user.id, Entry.other_id == user.id))
        .order_by(Entry.created_at.desc(), Entry.id.desc())
        .limit(limit)
        .all()
    )
