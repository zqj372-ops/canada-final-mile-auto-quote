from __future__ import annotations

import os
import sys
from argparse import ArgumentParser
from datetime import date, datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.api.db.session import get_database_url
from apps.api.services.quote_release_service import publish_quote_release


def main() -> None:
    parser = ArgumentParser(description="Publish the database-owned quote release manifest.")
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--service-version", required=True)
    parser.add_argument("--rule-version", required=True)
    parser.add_argument("--data-version", required=True)
    parser.add_argument("--published-at", required=True, help="Timezone-aware ISO-8601 timestamp")
    parser.add_argument("--valid-from", required=True, type=date.fromisoformat)
    parser.add_argument("--valid-to", required=True, type=date.fromisoformat)
    parser.add_argument("--test-data", required=True, choices=("true", "false"))
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL") or get_database_url())
    args = parser.parse_args()

    engine = create_engine(args.database_url)
    with Session(engine) as session:
        publish_quote_release(
            session,
            release_id=args.release_id,
            service_version=args.service_version,
            rule_version=args.rule_version,
            data_version=args.data_version,
            published_at=datetime.fromisoformat(args.published_at.replace("Z", "+00:00")),
            valid_from=args.valid_from,
            valid_to=args.valid_to,
            test_data=args.test_data == "true",
        )


if __name__ == "__main__":
    main()
