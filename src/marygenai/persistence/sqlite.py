from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

DEFAULT_SQLITE_FILENAME = "marygenai.sqlite"


def sqlite_database_path(data_dir: Path) -> Path:
    return data_dir / "db" / DEFAULT_SQLITE_FILENAME


@contextmanager
def connect_sqlite(database_path: Path) -> Iterator[sqlite3.Connection]:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
