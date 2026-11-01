from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


def get_database_url() -> str:
    return f"sqlite:///{settings.sqlite_file.as_posix()}"


engine = create_engine(get_database_url(), future=True,
                       connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def init_database() -> None:
    from app.database.models import ProductJob  # noqa: F401

    settings.sqlite_file.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _remove_legacy_catalog_tables()
    _add_missing_columns()


def _remove_legacy_catalog_tables() -> None:
    with engine.begin() as connection:
        for table in ("catalog_index_runs", "catalog_products", "csv_enrichment_jobs"):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table}"'))


def _add_missing_columns() -> None:
    additions = {
    }
    with engine.begin() as connection:
        inspector = inspect(connection)
        for table, columns in additions.items():
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, definition in columns.items():
                if name not in existing:
                    connection.execute(text(
                        f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}'))
