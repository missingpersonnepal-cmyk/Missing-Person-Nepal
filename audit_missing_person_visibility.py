from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from urllib.parse import urlparse


def resolve_sqlite_path() -> Path:
    raw = os.getenv("DATABASE_URL", "sqlite:///./missing_person_dev.db").strip()
    if not raw.startswith("sqlite"):
        raise SystemExit(
            "This audit script is intentionally read-only and currently supports the local SQLite database only.\n"
            f"DATABASE_URL is: {raw!r}"
        )

    if raw.startswith("sqlite:///"):
        value = raw[len("sqlite:///") :]
    else:
        raise SystemExit(f"Unsupported SQLite URL: {raw!r}")

    path = Path(value)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def print_rows(title: str, rows: list[sqlite3.Row], limit: int = 50) -> None:
    print()
    print(title)
    print("-" * len(title))
    if not rows:
        print("(none)")
        return
    for row in rows[:limit]:
        print(" | ".join("" if value is None else str(value) for value in row))
    if len(rows) > limit:
        print(f"... plus {len(rows) - limit} more")


def main() -> int:
    db_path = resolve_sqlite_path()
    print(f"Database: {db_path}")

    if not db_path.is_file():
        print("ERROR: SQLite database file was not found.")
        return 2

    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row

    required = [
        "mp_disasters",
        "mp_missing_people",
        "mp_submissions",
    ]
    missing = [name for name in required if not table_exists(conn, name)]
    if missing:
        print("ERROR: Required tables are missing:", ", ".join(missing))
        return 3

    has_state = table_exists(conn, "mp_person_case_states")

    disasters = conn.execute(
        "SELECT id, code, name, active FROM mp_disasters ORDER BY id"
    ).fetchall()

    print()
    print("VISIBILITY AUDIT")
    print("================")
    print("Public Missing Persons Hub rule:")
    print("  published = 1, archived = 0, case status = missing")
    print()
    print(f"Case-status table present: {has_state}")

    for disaster in disasters:
        did = disaster["id"]
        pending = conn.execute(
            """
            SELECT COUNT(*)
            FROM mp_submissions
            WHERE disaster_id = ?
              AND status = 'pending'
              AND kind = 'missing_report'
            """,
            (did,),
        ).fetchone()[0]

        unpublished = conn.execute(
            """
            SELECT COUNT(*)
            FROM mp_missing_people
            WHERE disaster_id = ?
              AND archived = 0
              AND published = 0
            """,
            (did,),
        ).fetchone()[0]

        if has_state:
            live = conn.execute(
                """
                SELECT COUNT(*)
                FROM mp_missing_people p
                LEFT JOIN mp_person_case_states s ON s.person_id = p.id
                WHERE p.disaster_id = ?
                  AND p.archived = 0
                  AND p.published = 1
                  AND COALESCE(s.status, 'missing') = 'missing'
                """,
                (did,),
            ).fetchone()[0]
            found = conn.execute(
                """
                SELECT COUNT(*)
                FROM mp_missing_people p
                JOIN mp_person_case_states s ON s.person_id = p.id
                WHERE p.disaster_id = ?
                  AND p.archived = 0
                  AND s.status = 'found'
                """,
                (did,),
            ).fetchone()[0]
            identified = conn.execute(
                """
                SELECT COUNT(*)
                FROM mp_missing_people p
                JOIN mp_person_case_states s ON s.person_id = p.id
                WHERE p.disaster_id = ?
                  AND p.archived = 0
                  AND s.status = 'identified'
                """,
                (did,),
            ).fetchone()[0]
        else:
            live = conn.execute(
                """
                SELECT COUNT(*)
                FROM mp_missing_people
                WHERE disaster_id = ?
                  AND archived = 0
                  AND published = 1
                """,
                (did,),
            ).fetchone()[0]
            found = 0
            identified = 0

        print()
        print(
            f"[{did}] {disaster['name']} ({disaster['code']})"
            f" | active={bool(disaster['active'])}"
        )
        print(f"  Pending submissions : {pending}")
        print(f"  Unpublished masters : {unpublished}")
        print(f"  LIVE missing        : {live}")
        print(f"  Found alive         : {found}")
        print(f"  Identified/deceased : {identified}")

    pending_rows = conn.execute(
        """
        SELECT s.id, d.name AS disaster, COALESCE(s.name, '(no name)') AS name,
               s.status, s.social_url
        FROM mp_submissions s
        JOIN mp_disasters d ON d.id = s.disaster_id
        WHERE s.status = 'pending'
          AND s.kind = 'missing_report'
        ORDER BY s.id DESC
        """
    ).fetchall()
    print_rows(
        "PENDING missing-person submissions (not public yet)",
        pending_rows,
    )

    unpublished_rows = conn.execute(
        """
        SELECT p.id, p.case_number, d.name AS disaster, p.name,
               p.published, p.archived
        FROM mp_missing_people p
        JOIN mp_disasters d ON d.id = p.disaster_id
        WHERE p.archived = 0
          AND p.published = 0
        ORDER BY p.id DESC
        """
    ).fetchall()
    print_rows(
        "UNPUBLISHED master cases (not public yet)",
        unpublished_rows,
    )

    if has_state:
        live_rows = conn.execute(
            """
            SELECT p.id, p.case_number, d.name AS disaster, p.name,
                   COALESCE(s.status, 'missing') AS case_status
            FROM mp_missing_people p
            JOIN mp_disasters d ON d.id = p.disaster_id
            LEFT JOIN mp_person_case_states s ON s.person_id = p.id
            WHERE p.archived = 0
              AND p.published = 1
              AND COALESCE(s.status, 'missing') = 'missing'
            ORDER BY p.id DESC
            """
        ).fetchall()
    else:
        live_rows = conn.execute(
            """
            SELECT p.id, p.case_number, d.name AS disaster, p.name,
                   'missing' AS case_status
            FROM mp_missing_people p
            JOIN mp_disasters d ON d.id = p.disaster_id
            WHERE p.archived = 0
              AND p.published = 1
            ORDER BY p.id DESC
            """
        ).fetchall()
    print_rows("LIVE public missing-person cases", live_rows)

    print()
    print("READ-ONLY AUDIT COMPLETE")
    print("No database rows were changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
