import os
import sys

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("BOT_PASSWORD", "secret")
os.environ.setdefault("DATABASE_URL", "sqlite://")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import database


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(database, "SessionLocal", Session)
    import models  # noqa: F401
    database.Base.metadata.create_all(engine)
    s = Session()
    yield s
    s.close()
