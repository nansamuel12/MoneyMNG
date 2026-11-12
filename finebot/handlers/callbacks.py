"""All inline-button presses."""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from database import session_scope
from handlers import flow, ui
from handlers.ui import money
from models import User, utcnow
from services import store

logger = logging.getLogger(__name__)
name = store.display_name


async def safe_edit(query, text: str):
    try:
        await query.edit_message_text(text)
    except Exception:
        pass


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = (query.data or "").split(":")

    with session_scope() as db:
        user = store.get_or_create_user(db, update.effective_user)
        if not user.is_authenticated:
            return await safe_edit(query, "Please send /start first.")

        kind = parts[0]
        try:
            if kind == "r" and len(parts) == 3:
                await on_respond(update, context, db, user, int(parts[1]), parts[2] == "y")
            elif kind == "c" and len(parts) == 2:
                await on_cancel(update, context, db, user, int(parts[1]))
            elif kind == "pick" and len(parts) == 3:
                await on_pick(update, context, db, user, parts[1], int(parts[2]))
            elif kind == "payall" and len(parts) == 2:
                await on_pay_all(update, context, db, user, int(parts[1]))
            elif kind == "skipnote":
                await safe_edit(query, "⏭ No reason added.")
                await flow.finish_fine(update, context, db, user, note=None)
            elif kind == "abort":
                context.user_data.pop("flow", None)
                await safe_edit(query, "✖ Cancelled.")
        except ValueError:
            await safe_edit(query, "⚠️ Invalid button.")


async def on_respond(update, context, db, user, entry_id: int, accept: bool):
    query = update.callback_query
    entry, err = store.respond(db, entry_id, user, accept)
    if err:
        return await safe_edit(query, f"⚠️ {err}")

    creator, other = entry.creator, entry.other
    amount = money(entry.amount_cents)
    # who owes whom after this answer
    debtor, creditor = (other, creator) if entry.kind == "fine" else (creator, other)
    led = store.owed(db, debtor, creditor)
    after = money(led.owed) if led.owed else "nothing — all paid 🎉"

    if entry.kind == "fine" and accept:
        mine = f"✅ You accepted the fine of {amount} from {name(creator)}.\nYou now owe {name(creator)}: {after}"
        theirs = f"✅ {name(other)} accepted your fine of {amount}.\n{name(other)} now owes you: {after}"
    elif entry.kind == "fine":
        mine = f"❌ You rejected the fine of {amount} from {name(creator)}."
        theirs = f"❌ {name(other)} rejected your fine of {amount}."
    elif accept:
        mine = f"✅ You confirmed {name(creator)}'s payment of {amount}.\n{name(creator)} now owes you: {after}"
        theirs = f"✅ {name(other)} confirmed your payment of {amount}.\nYou now owe {name(other)}: {after}"
    else:
        mine = f"❌ You said you did not receive {amount} from {name(creator)}."
        theirs = f"❌ {name(other)} says they did not receive your payment of {amount}."

    await safe_edit(query, mine)
    try:
        await context.bot.send_message(creator.telegram_id, theirs)
    except Exception:
        logger.warning("Could not notify %s", creator.telegram_id)


async def on_cancel(update, context, db, user, entry_id: int):
    query = update.callback_query
    entry, err = store.cancel(db, entry_id, user)
    if err:
        return await safe_edit(query, f"⚠️ {err}")
    await safe_edit(query, f"🚫 Cancelled: {ui.entry_line(entry, user)}")
    try:
        await context.bot.send_message(
            entry.other.telegram_id,
            f"🚫 {name(user)} cancelled their request of {money(entry.amount_cents)}.",
        )
    except Exception:
        pass


async def on_pick(update, context, db, user, action: str, partner_id: int):
    partner = db.get(User, partner_id)
    if partner is None or not store.are_partners(db, user.id, partner.id):
        return await safe_edit(update.callback_query, "⚠️ You are not connected with this person.")
    await safe_edit(update.callback_query, f"👤 {name(partner)}")
    if action == "fine":
        await flow.begin_fine(update, context, partner)
    else:
        await flow.begin_pay(update, context, db, user, partner)


async def on_pay_all(update, context, db, user, partner_id: int):
    partner = db.get(User, partner_id)
    if partner is None or not store.are_partners(db, user.id, partner.id):
        return await safe_edit(update.callback_query, "⚠️ You are not connected with this person.")
    led = store.owed(db, user, partner, utcnow())
    if led.owed <= 0:
        return await safe_edit(update.callback_query, f"🎉 You don't owe {name(partner)} anything.")
    await safe_edit(update.callback_query, f"💰 Paid all: {money(led.owed)}")
    await flow.finish_payment(update, context, db, user, partner, led.owed)
