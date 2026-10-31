from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def init_db(bind=None) -> None:
    from app import models  # noqa: F401 — ensure models are registered

    bind = bind or engine
    Base.metadata.create_all(bind=bind)
    add_missing_columns(bind)


def add_missing_columns(bind) -> list[str]:
    """Minimal forward-only migration: add columns that exist in the models
    but not yet in an existing table (create_all never alters tables). Lets
    the user keep their collected data across app updates. New columns must
    be nullable or have a server-side default."""
    added = []
    insp = inspect(bind)
    with bind.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                ddl_type = col.type.compile(dialect=bind.dialect)
                default = ""
                if col.server_default is not None:
                    arg = col.server_default.arg
                    default = " DEFAULT '" + str(arg).replace("'", "''") + "'" if isinstance(arg, str) else f" DEFAULT {arg}"
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl_type}{default}'))
                added.append(f"{table.name}.{col.name}")
    return added


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
