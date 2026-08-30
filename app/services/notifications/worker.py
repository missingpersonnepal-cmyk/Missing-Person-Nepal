from __future__ import annotations

import argparse

from ...database import SessionLocal
from .service import drain_pending_notifications


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    with SessionLocal() as db:
        result = drain_pending_notifications(db, limit=args.limit)
        db.commit()
    print(result)


if __name__ == "__main__":
    main()
