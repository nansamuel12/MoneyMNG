import hmac
import logging
import time

from telegram import ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes

from config import BOT_PASSWORD
from database import session_scope
from handlers import ui
from services import store

logger = logging.getLogger(__name__)

MAX_TRIES = 5
LOCK_SECONDS = 300
_attempts: dict[int, list] = {}  # telegram_id -> [wrong_count, locked_until]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with session_scope() as db:
        user = store.get_or_create_user(db, update.effective_user)
        if context.args:  # opened from an invite link
            context.user_data["pending_invite"] = context.args[0]
        if not user.is_authenticated:
            await ui.send(
                update,
                "👋 Welcome!\n\n🔐 This bot is private. Please send the password.\n"
                "You only need to do this once.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return
        await after_login(update, context, db, user, first_time=False)


async def try_password(update: Update, context: ContextTypes.DEFAULT_TYPE, db, user, text: str):
    tg_id = update.effective_user.id
    rec = _attempts.setdefault(tg_id, [0, 0.0])
    now = time.time()
    if rec[1] > now:
        minutes = int((rec[1] - now) // 60) + 1
        await ui.send(update, f"⏳ Too many wrong attempts. Try again in {minutes} min.")
        return

    ok = hmac.compare_digest(text.encode(), BOT_PASSWORD.encode())
    try:  # don't leave the password visible in the chat
        await update.message.delete()
    except Exception:
        pass

    if ok:
        _attempts.pop(tg_id, None)
        user.is_authenticated = True
        db.commit()
        await after_login(update, context, db, user, first_time=True)
        return

    rec[0] += 1
    if rec[0] >= MAX_TRIES:
        rec[0], rec[1] = 0, now + LOCK_SECONDS
        await ui.send(update, "❌ Wrong password. Too many attempts — try again in 5 minutes.")
    else:
        await ui.send(update, f"❌ Wrong password. Try again ({MAX_TRIES - rec[0]} left).")


async def after_login(update, context, db, user, first_time: bool):
    name = update.effective_user.first_name or "there"
    await ui.send(
        update,
        f"✅ Welcome, {name}! You're in — I won't ask for the password again."
        if first_time else f"👋 Welcome back, {name}!",
        reply_markup=ui.MAIN_KEYBOARD,
    )
    code = context.user_data.pop("pending_invite", None)
    if code:
        await handle_invite(update, context, db, user, code)
    elif not store.partners_of(db, user):
        await send_invite_card(update, context, user)


async def handle_invite(update, context, db, user, code: str):
    other, status = store.link_partners(db, user, code)
    if status == "invalid":
        await ui.send(update, "⚠️ That invite link is not valid.")
    elif status == "self":
        await ui.send(update, "🙂 That's your own link. Send it to the other person.")
    elif status == "already":
        await ui.send(update, f"You are already connected with {store.display_name(other)}.")
    else:
        await ui.send(
            update,
            f"🎉 Connected with {store.display_name(other)}!\n"
            "Use ➕ Give Fine or 💰 I Paid whenever you need.",
        )
        try:
            await context.bot.send_message(
                other.telegram_id,
                f"🎉 {store.display_name(user)} joined using your link. You are now connected!",
            )
        except Exception:
            logger.warning("Could not notify inviter %s", other.telegram_id)


async def send_invite_card(update, context, user):
    link = f"https://t.me/{context.bot.username}?start={user.invite_code}"
    await ui.send(update, ui.invite_text(link), reply_markup=ui.invite_keyboard(link))
