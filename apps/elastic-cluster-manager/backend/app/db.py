from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_factory = None


def get_engine():
    global _engine, _factory
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True)
        _factory = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def session_factory() -> sessionmaker[Session]:
    get_engine()
    return _factory


def get_db() -> Iterator[Session]:
    with session_factory()() as db:
        yield db


def reset_engine() -> None:
    """Test hook: drop the cached engine so settings changes take effect."""
    global _engine, _factory
    if _engine is not None:
        _engine.dispose()
    _engine = _factory = None
