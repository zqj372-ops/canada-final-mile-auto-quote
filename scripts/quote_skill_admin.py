"""Manage quote-skill grants with trusted server database access; never print codes."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from apps.api.db.models import QuoteSkillGrant, User
from apps.api.db.session import get_session_factory
from apps.api.services.quote_skill_service import create_grant, public_grant


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    issue = sub.add_parser("issue")
    issue.add_argument("--username", required=True)
    issue.add_argument("--name", required=True)
    issue.add_argument("--output", required=True, help="New private file; contains the one-time code")
    listing = sub.add_parser("list")
    listing.add_argument("--username", required=True)
    revoke = sub.add_parser("revoke")
    revoke.add_argument("--grant", type=int, required=True)
    args = parser.parse_args()
    with get_session_factory()() as db:
        if args.command == "revoke":
            grant = db.get(QuoteSkillGrant, args.grant)
            if grant is None:
                parser.error("authorization not found")
            grant.enabled = False
            db.commit()
            result = {"id": grant.id, "revoked": True}
        else:
            user = db.scalar(select(User).where(User.username == args.username.strip().lower()))
            if user is None:
                parser.error("existing quote account not found; create an account through the existing user workflow")
            if args.command == "list":
                result = [public_grant(g) for g in db.scalars(select(QuoteSkillGrant).where(
                    QuoteSkillGrant.user_id == user.id).order_by(QuoteSkillGrant.id.desc()))]
            else:
                if not 1 <= len(args.name.strip()) <= 128:
                    parser.error("device name must contain 1 to 128 characters")
                output = Path(args.output).expanduser()
                # Verify exclusive private-file creation before issuing the code.
                fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                grant = None
                try:
                    with os.fdopen(fd, "w") as stream:
                        grant, code = create_grant(db, user, args.name.strip())
                        json.dump({"authorization_code": code, "expires_at": grant.code_expires_at,
                                   "username": user.username}, stream, default=str)
                        stream.write("\n")
                except Exception:
                    if grant is not None:
                        grant.enabled = False
                        db.commit()
                    output.unlink(missing_ok=True)
                    raise
                result = {"id": grant.id, "username": user.username, "name": grant.name,
                          "expires_at": grant.code_expires_at, "code_file": str(output)}
        print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
