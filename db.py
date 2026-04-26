"""SQLite schema, migrations, and connection helpers."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "inventory.db"
MIGRATIONS_DIR = ROOT / "migrations"

# Python 3.12 deprecated the default datetime adapter. Register an explicit
# ISO-8601 adapter to keep timestamps readable in the .db file and silence the
# DeprecationWarning. We don't register a converter — TIMESTAMP columns read
# back as ISO strings, which is what callers compare and serialize.
sqlite3.register_adapter(datetime, lambda v: v.isoformat())


def connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def current_version(conn: sqlite3.Connection) -> int:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version INTEGER PRIMARY KEY, applied_at TIMESTAMP NOT NULL)"
    )
    row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
    return row["v"] or 0


def _list_migrations() -> list[tuple[int, Path, Path]]:
    out: list[tuple[int, Path, Path]] = []
    for up in sorted(MIGRATIONS_DIR.glob("*.up.sql")):
        version = int(up.name.split("_", 1)[0])
        down = up.with_name(up.name.replace(".up.sql", ".down.sql"))
        if not down.exists():
            raise RuntimeError(f"missing down migration for {up.name}")
        out.append((version, up, down))
    return sorted(out, key=lambda t: t[0])


def migrate(conn: sqlite3.Connection, target: int | None = None) -> int:
    """Apply pending migrations up or down to `target` (or latest)."""
    version = current_version(conn)
    migrations = _list_migrations()
    if target is None:
        target = max((v for v, _, _ in migrations), default=0)

    if target > version:
        for v, up, _ in migrations:
            if version < v <= target:
                conn.executescript(up.read_text())
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) "
                    "VALUES (?, CURRENT_TIMESTAMP)",
                    (v,),
                )
                conn.commit()
                version = v
    elif target < version:
        for v, _, down in reversed(migrations):
            if target < v <= version:
                conn.executescript(down.read_text())
                conn.execute("DELETE FROM schema_migrations WHERE version=?", (v,))
                conn.commit()

    return current_version(conn)


if __name__ == "__main__":
    import sys

    arg = sys.argv[1] if len(sys.argv) > 1 else "up"
    with connect() as conn:
        if arg == "up":
            v = migrate(conn)
            print(f"migrated up to version {v}")
        elif arg == "down":
            target = int(sys.argv[2]) if len(sys.argv) > 2 else 0
            v = migrate(conn, target=target)
            print(f"migrated down to version {v}")
        elif arg == "version":
            print(current_version(conn))
        else:
            print(f"usage: python db.py [up | down [target] | version]")
            sys.exit(2)
