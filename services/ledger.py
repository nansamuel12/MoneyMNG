"""
Pure money logic (no database, no Telegram) so it is easy to test.

Rules
-----
* Every ACCEPTED fine is added to what the debtor owes.
* Every ACCEPTED payment is subtracted.
* Every full 7 days after a fine was accepted, +1% of that fine's unpaid
  PRINCIPAL is added as interest. Interest is never charged on interest
  (simple interest, not compound).
* A payment first clears interest, then principal, oldest fine first.
* When a fine's principal and interest are both 0 it is "paid" and stops growing.

Balance is always recomputed from the history, so it is always up to date
(no daily job that can be missed).
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable

WEEK = timedelta(days=7)


@dataclass
class FineLine:
    id: int
    amount: int
    accepted_at: datetime
    principal_left: int = 0
    interest_due: int = 0
    interest_total: int = 0
    paid_total: int = 0

    @property
    def owed(self) -> int:
        return self.principal_left + self.interest_due

    @property
    def is_paid(self) -> bool:
        return self.owed == 0


@dataclass
class Ledger:
    lines: list[FineLine] = field(default_factory=list)
    fined_total: int = 0      # sum of accepted fines
    interest_total: int = 0   # all interest added so far
    paid_total: int = 0       # accepted payments that were applied
    owed: int = 0             # what is still to pay right now
    next_interest_at: datetime | None = None


def compute_ledger(
    fines: Iterable[tuple[int, int, datetime]],      # (id, amount_cents, accepted_at)
    payments: Iterable[tuple[int, datetime]],        # (amount_cents, accepted_at)
    now: datetime,
    rate_percent: int = 1,
) -> Ledger:
    events = []  # (time, order, seq, kind, payload)  order: fine < tick < payment
    seq = 0
    for fid, amount, at in fines:
        if at > now:
            continue
        events.append((at, 0, seq, "fine", (fid, amount)))
        seq += 1
        k = 1
        while at + k * WEEK <= now:
            events.append((at + k * WEEK, 1, seq, "tick", fid))
            seq += 1
            k += 1
    for amount, at in payments:
        if at > now:
            continue
        events.append((at, 2, seq, "pay", amount))
        seq += 1
    events.sort(key=lambda e: e[:3])

    lines: dict[int, FineLine] = {}
    for at, _order, _seq, kind, payload in events:
        if kind == "fine":
            fid, amount = payload
            lines[fid] = FineLine(fid, amount, at, principal_left=amount)
        elif kind == "tick":
            line = lines[payload]
            if line.principal_left > 0:
                # 1% of the unpaid principal, rounded half-up to the cent
                interest = (line.principal_left * rate_percent + 50) // 100
                line.interest_due += interest
                line.interest_total += interest
        else:  # payment
            remaining = payload
            for line in lines.values():  # oldest first
                if remaining <= 0:
                    break
                x = min(remaining, line.interest_due)
                line.interest_due -= x
                remaining -= x
                y = min(remaining, line.principal_left)
                line.principal_left -= y
                remaining -= y
                line.paid_total += x + y

    ledger = Ledger(lines=list(lines.values()))
    for line in ledger.lines:
        ledger.fined_total += line.amount
        ledger.interest_total += line.interest_total
        ledger.paid_total += line.paid_total
        ledger.owed += line.owed
        if line.principal_left > 0:
            weeks = int((now - line.accepted_at) / WEEK)
            nxt = line.accepted_at + (weeks + 1) * WEEK
            if ledger.next_interest_at is None or nxt < ledger.next_interest_at:
                ledger.next_interest_at = nxt
    return ledger
