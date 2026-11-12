import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_PASSWORD = os.getenv("BOT_PASSWORD")
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# New database file (the old finebot.db is left untouched).
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///finebot_v2.db")

CURRENCY = os.getenv("CURRENCY", "Birr")
WEEKLY_INTEREST_PERCENT = int(os.getenv("WEEKLY_INTEREST_PERCENT", "1"))

if not BOT_TOKEN:
    raise ValueError(
        "BOT_TOKEN is missing. Create a file named .env next to main.py:\n\n"
        "BOT_TOKEN=your_bot_token_here\n"
        "BOT_PASSWORD=your_password_here\n"
    )

if not BOT_PASSWORD:
    raise ValueError("BOT_PASSWORD is missing in .env (it is asked once when a user joins).")
