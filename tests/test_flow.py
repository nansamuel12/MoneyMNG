"""Simulates two people using the bot (fake Telegram, real handlers + database)."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import database
from handlers import callbacks, flow, start as start_h, ui
from services import store


class Chat:
    def __init__(self, tid, name, bot):
        self.tg = SimpleNamespace(id=tid, username=None, full_name=name, first_name=name)
        self.sent = []
        self.bot = bot
        self.user_data = {}
        self.args = []
        bot.chats[tid] = self

    def ctx(self):
        return SimpleNamespace(bot=self.bot, user_data=self.user_data, args=self.args)

    def update(self, text=None, data=None):
        async def send_message(t, **kw):
            self.sent.append((t, kw.get("reply_markup")))
        chat = SimpleNamespace(send_message=send_message)
        msg = SimpleNamespace(text=text, delete=AsyncMock())
        q = None
        if data is not None:
            q = SimpleNamespace(data=data, answer=AsyncMock(), edit_message_text=AsyncMock())
        return SimpleNamespace(effective_user=self.tg, effective_chat=chat, message=msg, callback_query=q)

    @property
    def last(self):
        return self.sent[-1]


class Bot:
    username = "FineTestBot"

    def __init__(self):
        self.chats = {}

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        self.chats[chat_id].sent.append((text, reply_markup))


def say(c, text):
    asyncio.run(flow.on_text(c.update(text), c.ctx()))


def tap(c, data):
    u = c.update(data=data)
    asyncio.run(callbacks.on_callback(u, c.ctx()))
    return u.callback_query


def buttons(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data]


def test_whole_story(db):
    bot = Bot()
    abel, bete = Chat(1, "Abel", bot), Chat(2, "Bete", bot)

    # password only the first time
    asyncio.run(start_h.start(abel.update("/start"), abel.ctx()))
    assert "password" in abel.last[0].lower()
    say(abel, "wrong")
    assert "Wrong password" in abel.last[0]
    say(abel, "secret")
    assert any("won't ask for the password again" in t for t, _ in abel.sent)
    n = len(abel.sent)
    asyncio.run(start_h.start(abel.update("/start"), abel.ctx()))   # second /start: no password
    assert "Welcome back" in abel.sent[n][0]

    # Bete joins through Abel's invite link (password first, then auto-connect)
    code = store.get_or_create_user(db, abel.tg).invite_code
    bete.args = [code]
    asyncio.run(start_h.start(bete.update("/start " + code), bete.ctx()))
    assert "password" in bete.last[0].lower()
    say(bete, "secret")
    assert any("Connected with Abel" in t for t, _ in bete.sent)
    assert any("joined using your link" in t for t, _ in abel.sent)

    # Abel gives a fine: typed amount (float) + reason
    say(abel, ui.BTN_FINE)
    assert "How much" in abel.last[0]
    say(abel, "abc")
    assert "doesn't look like an amount" in abel.last[0]
    say(abel, "100.5")
    say(abel, "was late")
    assert "Waiting for them to accept" in abel.last[0]
    text, markup = bete.last
    assert "gave you a fine" in text and "100.50 Birr" in text and "was late" in text
    accept = buttons(markup)[0]

    # the sender cannot accept his own fine
    fid = accept.split(":")[1]
    q = tap(abel, f"r:{fid}:y")
    assert "not for you" in q.edit_message_text.call_args[0][0]

    # Bete accepts
    q = tap(bete, accept)
    assert "You now owe Abel: 100.50 Birr" in q.edit_message_text.call_args[0][0]
    assert "now owes you: 100.50 Birr" in abel.last[0]
    tap(bete, accept)  # pressing twice is harmless
    say(bete, ui.BTN_BALANCE)
    assert "🔴 You owe Abel: 100.50 Birr" in bete.last[0] and "Next +1%" in bete.last[0]

    # Bete says "I paid 50"
    say(bete, ui.BTN_PAID)
    assert "You owe Abel: 100.50 Birr" in bete.last[0]
    say(bete, "500")
    assert "only owe 100.5" in bete.last[0]
    say(bete, "50")
    text, markup = abel.last
    assert "says they paid you" in text and "50 Birr" in text
    q = tap(abel, buttons(markup)[0])
    assert "now owes you: 50.50 Birr" in q.edit_message_text.call_args[0][0]
    assert "You now owe Abel: 50.50 Birr" in bete.last[0]

    # pay the rest with one tap
    say(bete, ui.BTN_PAID)
    _, markup = bete.last
    tap(bete, [d for d in buttons(markup) if d.startswith("payall")][0])
    q = tap(abel, buttons(abel.last[1])[0])
    assert "all paid" in q.edit_message_text.call_args[0][0]
    say(bete, ui.BTN_PAID)
    assert "don't owe" in bete.last[0]

    # reject + cancel paths, pending list, history
    say(abel, ui.BTN_FINE); say(abel, "20"); tap(abel, "skipnote")
    tap(bete, buttons(bete.last[1])[1])           # Bete rejects
    assert "rejected your fine" in abel.last[0]
    say(abel, ui.BTN_FINE); say(abel, "30"); say(abel, "x")
    say(abel, ui.BTN_PENDING)
    assert "Waiting for Bete" in abel.last[0]
    q = tap(abel, buttons(abel.last[1])[0])
    assert "Cancelled" in q.edit_message_text.call_args[0][0]
    assert "cancelled their request" in bete.last[0]
    say(abel, ui.BTN_HISTORY)
    assert "You fined Bete" in abel.last[0] and "❌" in abel.last[0] and "🚫" in abel.last[0]
