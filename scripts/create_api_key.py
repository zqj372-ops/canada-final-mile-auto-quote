import argparse
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.api.db.repositories.api_key_repository import APIKeyRepository
from apps.api.db.session import get_session_factory


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an API key and print the plaintext once.")
    parser.add_argument("--name", required=True)
    parser.add_argument("--role", required=True, choices=["admin", "operator", "sales", "viewer"])
    parser.add_argument("--disabled", action="store_true")
    args = parser.parse_args()

    session_factory = get_session_factory()
    with session_factory() as session:
        record, plain_key = APIKeyRepository(session).create_key(
            name=args.name,
            role=args.role,
            enabled=not args.disabled,
        )

    print(f"id={record.id}")
    print(f"name={record.name}")
    print(f"role={record.role}")
    print(f"api_key={plain_key}")


if __name__ == "__main__":
    main()
