import argparse
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.api.db.repositories.user_repository import UserRepository
from apps.api.db.session import get_session_factory


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or update a login user.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--display-name")
    parser.add_argument("--role", required=True, choices=["admin", "operator", "sales", "viewer"])
    parser.add_argument("--disabled", action="store_true")
    parser.add_argument(
        "--update-if-exists",
        action="store_true",
        help="Update role/display name/password when the username already exists.",
    )
    args = parser.parse_args()

    session_factory = get_session_factory()
    with session_factory() as session:
        repository = UserRepository(session)
        existing = repository.get_by_username(args.username)
        if existing is not None:
            if not args.update_if_exists:
                print(f"username={existing.username}")
                print(f"id={existing.id}")
                print("status=exists")
                return
            record = repository.update_user(
                existing.id,
                display_name=args.display_name or existing.display_name,
                enabled=not args.disabled,
                password=args.password,
                role=args.role,
            )
            status = "updated"
        else:
            record = repository.create_user(
                username=args.username,
                password=args.password,
                display_name=args.display_name,
                role=args.role,
                enabled=not args.disabled,
            )
            status = "created"

    if record is None:
        raise RuntimeError("User was not created or updated.")
    print(f"id={record.id}")
    print(f"username={record.username}")
    print(f"display_name={record.display_name}")
    print(f"role={record.role}")
    print(f"enabled={record.enabled}")
    print(f"status={status}")


if __name__ == "__main__":
    main()
