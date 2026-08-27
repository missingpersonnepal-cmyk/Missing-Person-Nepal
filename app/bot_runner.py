from __future__ import annotations

import argparse

from sqlalchemy import select

from .database import SessionLocal
from .models import Disaster
from .services.discovery import discover_candidates


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one bounded public social discovery pass")
    parser.add_argument("--event", help="Disaster code, e.g. RF. Defaults to the newest active event.")
    parser.add_argument(
        "--platform",
        default="facebook",
        choices=["facebook", "web", "instagram", "tiktok", "x", "reddit"],
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        if args.event:
            disaster = db.scalar(select(Disaster).where(Disaster.code == args.event.upper()))
        else:
            disaster = db.scalar(
                select(Disaster).where(Disaster.active.is_(True)).order_by(Disaster.start_date.desc()).limit(1)
            )
        if disaster is None:
            print("No matching active disaster event found.")
            return 2
        added = discover_candidates(db, disaster, platform=args.platform)
        db.commit()
        print(f"Discovery complete: event={disaster.code} platform={args.platform} new_candidates={added}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
