"""Menu buttons and the typed steps (amount, reason)."""
import logging

from telegram import InlineKeyboardButton, Update
from telegram.ext import ContextTypes

from database import session_scope
from handlers import start as start_h
from handlers import ui
from handlers.ui import money, send
from models import User, utcnow
from services import store
from services.money import parse_amount

logger = logging.getLogger(__name__)
name = store.display_name


# ---------- router: every normal text message comes here ----------

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    with session_scope() as db:
        user = store.get_or_create_user(db, update.effective_user)

        if not user.is_authenticated:           # first time only
            await start_h.try_password(update, context, db, user, text)
            return

        action = MENU.get(text)
        if action:                               # a menu button always wins
            context.user_data.pop("flow", None)
            await action(update, context, db, user)
            return

        flow = context.user_data.get("flow")
        if flow:
            await handle_flow(update, context, db, user, text, flow)
            return

        await send(update, "Please use the buttons below 👇", reply_markup=ui.MAIN_KEYBOARD)


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("flow", None)
    await send(update, "Cancelled.", reply_markup=ui.MAIN_KEYBOARD)


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with session_scope() as db:
        user = store.get_or_create_user(db, update.effective_user)
        if not user.is_authenticated:
            await send(update, "Please send /start first.")
            return
    await send(update, "Choose an option 👇", reply_markup=ui.MAIN_KEYBOARD)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with session_scope() as db:
        user = store.get_or_create_user(db, update.effective_user)
        if not user.is_authenticated:
            await send(update, "Please send /start first.")
            return
    await send(update, ui.HELP_TEXT, reply_markup=ui.MAIN_KEYBOARD)


# ---------- menu actions ----------

async def no_partner(update, context, user):
    await send(update, "You are not connected with anyone yet. Send your invite link first 👇")
    await start_h.send_invite_card(update, context, user)


async def act_fine(update, context, db, user):
    partners = store.partners_of(db, user)
    if not partners:
        return await no_partner(update, context, user)
    if len(partners) == 1:
        return await begin_fine(update, context, partners[0])
    await send(update, "Who is the fine for?", reply_markup=ui.partner_picker(partners, "fine"))


async def act_paid(update, context, db, user):
    partners = store.partners_of(db, user)
    if not partners:
        return await no_partner(update, context, user)
    if len(partners) == 1:
        return await begin_pay(update, context, db, user, partners[0])
    await send(update, "Who did you pay?", reply_markup=ui.partner_picker(partners, "pay"))


async def act_balance(update, context, db, user):
    partners = store.partners_of(db, user)
    if not partners:
        return await no_partner(update, context, user)
    now = utcnow()
    blocks = []
    for p in partners:
        mine = store.owed(db, user, p, now)      # I owe p
        theirs = store.owed(db, p, user, now)    # p owes me
        lines = [f"👤 {name(p)}"]
        if not mine.lines and not theirs.lines:
            lines.append("Nothing yet.")
        if mine.lines:
            lines.append(ui.ledger_block(f"You owe {name(p)}", mine, "🔴", now))
        if theirs.lines:
            lines.append(ui.ledger_block(f"{name(p)} owes you", theirs, "🟢", now))
        if mine.owed and theirs.owed:
            net = theirs.owed - mine.owed
            who = f"{name(p)} owes you" if net > 0 else f"You owe {name(p)}"
            lines.append(f"⚖️ Net: {who} {money(abs(net))}")
        blocks.append("\n".join(lines))
    await send(update, "\n\n".join(blocks))


async def act_pending(update, context, db, user):
    incoming = store.pending_for(db, user)
    outgoing = store.waiting_on(db, user)
    if not incoming and not outgoing:
        return await send(update, "✅ Nothing pending.")
    for e in incoming:
        await send(update, ui.request_text(e), reply_markup=ui.respond_keyboard(e))
    for e in outgoing:
        await send(update, f"⏳ Waiting for {name(e.other)} to answer:\n{ui.entry_line(e, user)}",
                   reply_markup=ui.cancel_request_keyboard(e.id))


async def act_history(update, context, db, user):
    rows = store.history(db, user)
    if not rows:
        return await send(update, "No history yet.")
    await send(update, "📋 Last entries\n\n" + "\n".join(ui.entry_line(e, user) for e in rows))


async def act_invite(update, context, db, user):
    await start_h.send_invite_card(update, context, user)


async def act_help(update, context, db, user):
    await send(update, ui.HELP_TEXT, reply_markup=ui.MAIN_KEYBOARD)


MENU = {
    ui.BTN_FINE: act_fine,
    ui.BTN_PAID: act_paid,
    ui.BTN_BALANCE: act_balance,
    ui.BTN_PENDING: act_pending,
    ui.BTN_HISTORY: act_history,
    ui.BTN_INVITE: act_invite,
    ui.BTN_HELP: act_help,
}


# ---------- fine flow ----------

async def begin_fine(update, context, partner: User):
    context.user_data["flow"] = {"type": "fine", "partner_id": partner.id, "step": "amount"}
    await send(update, f"➕ Fine for {name(partner)}\n\nHow much? Just type the amount (like 50 or 75.5):",
               reply_markup=ui.abort_keyboard())


async def finish_fine(update, context, db, user, note: str | None):
    flow = context.user_data.pop("flow", None)
    if not flow or flow.get("type") != "fine" or "amount" not in flow:
        return await send(update, "That request expired. Tap ➕ Give Fine to start again.")
    partner = db.get(User, flow["partner_id"])
    entry, err = store.create_fine(db, user, partner, flow["amount"], note)
    if err:
        return await send(update, f"⚠️ {err}")
    delivered = await notify_request(context, entry)
    msg = f"📨 Sent to {name(partner)}: {money(entry.amount_cents)}\nWaiting for them to accept."
    if not delivered:
        msg += "\n\n⚠️ I couldn't message them. Ask them to open the bot once."
    await send(update, msg)


# ---------- payment flow ----------

async def begin_pay(update, context, db, user, partner: User):
    led = store.owed(db, user, partner)
    if led.owed <= 0:
        context.user_data.pop("flow", None)
        return await send(update, f"🎉 You don't owe {name(partner)} anything.")
    context.user_data["flow"] = {"type": "pay", "partner_id": partner.id, "step": "amount"}
    await send(
        update,
        f"💰 You owe {name(partner)}: {money(led.owed)}\n\n"
        "How much did you pay? Type the amount, or tap the button:",
        reply_markup=ui.abort_keyboard(
            [InlineKeyboardButton(f"Paid all ({money(led.owed)})", callback_data=f"payall:{partner.id}")]
        ),
    )


async def finish_payment(update, context, db, user, partner: User, cents: int):
    entry, err = store.create_payment(db, user, partner, cents)
    if err:
        return await send(update, f"⚠️ {err}")
    context.user_data.pop("flow", None)
    delivered = await notify_request(context, entry)
    msg = f"📨 Sent to {name(partner)}: you paid {money(entry.amount_cents)}\nWaiting for them to confirm."
    if not delivered:
        msg += "\n\n⚠️ I couldn't message them. Ask them to open the bot once."
    await send(update, msg)


# ---------- typed steps ----------

async def handle_flow(update, context, db, user, text: str, flow: dict):
    if flow["type"] == "fine" and flow["step"] == "note":
        return await finish_fine(update, context, db, user, note=text[:200])

    cents = parse_amount(text)
    if cents is None:
        return await send(update, "That doesn't look like an amount.\nType a number like 50 or 75.5",
                          reply_markup=ui.abort_keyboard())

    if flow["type"] == "fine":
        flow["amount"], flow["step"] = cents, "note"
        await send(
            update,
            f"Amount: {money(cents)}\n\nWhy? Type the reason, or tap Skip.",
            reply_markup=ui.abort_keyboard([InlineKeyboardButton("⏭ Skip", callback_data="skipnote")]),
        )
    else:
        partner = db.get(User, flow["partner_id"])
        await finish_payment(update, context, db, user, partner, cents)


async def notify_request(context, entry) -> bool:
    try:
        await context.bot.send_message(
            entry.other.telegram_id, ui.request_text(entry), reply_markup=ui.respond_keyboard(entry)
        )
        return True
    except Exception:
        logger.exception("Could not deliver request %s", entry.id)
        return False
