"""Buttons and message texts (plain text only, so names/notes can never break formatting)."""
from datetime import datetime
from urllib.parse import quote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from config import CURRENCY, WEEKLY_INTEREST_PERCENT
from models import Entry, User, utcnow
from services.ledger import Ledger
from services.money import fmt
from services.store import display_name

BTN_FINE = "➕ Give Fine"
BTN_PAID = "💰 I Paid"
BTN_BALANCE = "📊 Balance"
BTN_PENDING = "🔔 Pending"
BTN_HISTORY = "📋 History"
BTN_INVITE = "🔗 Invite"
BTN_HELP = "❓ Help"

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [[BTN_FINE, BTN_PAID], [BTN_BALANCE, BTN_PENDING], [BTN_HISTORY, BTN_INVITE], [BTN_HELP]],
    resize_keyboard=True,
)


def money(cents: int) -> str:
    return f"{fmt(cents)} {CURRENCY}"


async def send(update, text: str, **kwargs):
    return await update.effective_chat.send_message(text, **kwargs)


# ---------- keyboards ----------

def respond_keyboard(entry: Entry) -> InlineKeyboardMarkup:
    yes, no = ("✅ Accept", "❌ Reject") if entry.kind == "fine" else ("✅ Yes, received", "❌ No")
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(yes, callback_data=f"r:{entry.id}:y"),
        InlineKeyboardButton(no, callback_data=f"r:{entry.id}:n"),
    ]])


def cancel_request_keyboard(entry_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Cancel request", callback_data=f"c:{entry_id}")]])


def abort_keyboard(extra: list[InlineKeyboardButton] | None = None) -> InlineKeyboardMarkup:
    rows = []
    if extra:
        rows.append(extra)
    rows.append([InlineKeyboardButton("✖ Cancel", callback_data="abort")])
    return InlineKeyboardMarkup(rows)


def partner_picker(partners: list[User], action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(display_name(p), callback_data=f"pick:{action}:{p.id}")] for p in partners]
    )


def invite_keyboard(link: str) -> InlineKeyboardMarkup:
    share = f"https://t.me/share/url?url={quote(link)}&text={quote('Join me on FineBot:')}"
    return InlineKeyboardMarkup([[InlineKeyboardButton("📤 Send link to my partner", url=share)]])


# ---------- texts ----------

def request_text(entry: Entry) -> str:
    """What the person who must answer sees."""
    who = display_name(entry.creator)
    if entry.kind == "fine":
        return (f"⚖️ {who} gave you a fine\n\n"
                f"Amount: {money(entry.amount_cents)}\n"
                f"Reason: {entry.note or '—'}\n\n"
                "Do you accept it?")
    return (f"💰 {who} says they paid you\n\n"
            f"Amount: {money(entry.amount_cents)}\n\n"
            "Did you receive it?")


def entry_line(entry: Entry, me: User) -> str:
    icon = {"pending": "⏳", "accepted": "✅", "rejected": "❌", "cancelled": "🚫"}[entry.status]
    date = (entry.created_at or utcnow()).strftime("%d %b")
    mine = entry.creator_id == me.id
    other = display_name(entry.other if mine else entry.creator)
    amount = money(entry.amount_cents)
    if entry.kind == "fine":
        what = f"You fined {other}" if mine else f"{other} fined you"
    else:
        what = f"You paid {other}" if mine else f"{other} paid you"
    return f"{icon} {date} · {what} · {amount}"


def _when(dt: datetime, now: datetime) -> str:
    days = (dt - now).days
    return f"in {days} day{'s' if days != 1 else ''}" if days >= 1 else "within 24h"


def ledger_block(title: str, led: Ledger, icon: str, now: datetime | None = None) -> str:
    now = now or utcnow()
    if led.owed == 0:
        return f"✅ {title}: all paid"
    lines = [
        f"{icon} {title}: {money(led.owed)}",
        f"   Fines {fmt(led.fined_total)} · Interest +{fmt(led.interest_total)} · Paid −{fmt(led.paid_total)}",
    ]
    if led.next_interest_at:
        lines.append(
            f"   Next +{WEEKLY_INTEREST_PERCENT}% on {led.next_interest_at.strftime('%d %b')} "
            f"({_when(led.next_interest_at, now)})"
        )
    return "\n".join(lines)


def invite_text(link: str) -> str:
    return ("🔗 Your personal invite link:\n\n"
            f"{link}\n\n"
            "Send it to the person you want to connect with. When they tap it, "
            "you are connected and can start.")


HELP_TEXT = (
    "📖 How FineBot works\n\n"
    "1️⃣ Tap 🔗 Invite and send your link to the other person.\n"
    "2️⃣ ➕ Give Fine — enter an amount. The other person gets a message and taps Accept or Reject.\n"
    "3️⃣ 💰 I Paid — enter what you paid. The person who received it taps Yes or No.\n"
    "4️⃣ 📊 Balance — see who owes what.\n\n"
    f"All accepted fines are added together, accepted payments are subtracted. "
    f"Every week {WEEKLY_INTEREST_PERCENT}% of the unpaid fine amount is added "
    "(interest is never charged on interest).\n\n"
    "Amounts can be whole numbers or decimals, like 50 or 75.5."
)
