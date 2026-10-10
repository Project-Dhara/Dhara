"""
Admin CLI to provision a DHARA login. Self-serve signup may also be enabled
via ENABLE_SIGNUP; this script is the admin path for locked-down environments.

Usage (from backend/):
    python scripts/create_user.py aparajita@peopleplus.ai 'some-password' --name "Aparajita" --dept "DES"
"""

import argparse
import os
import sys

from dotenv import load_dotenv

# Run directly (`python scripts/create_user.py`), so make sibling packages
# under backend/ (this script's parent dir) importable regardless of cwd.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

from app.core import security as _auth
from app.db.repositories import organisations as org_repo
from app.db.repositories import users as user_repo
from app.db.session import session_scope


def main():
    parser = argparse.ArgumentParser(description="Create or update a DHARA login.")
    parser.add_argument("email", help="Login email, e.g. name@organization.domain")
    parser.add_argument("password")
    parser.add_argument("--name", default=None)
    parser.add_argument("--dept", default=None)
    parser.add_argument(
        "--role",
        default=None,
        help="Membership role: administrator | data_steward | data_user "
        "(default: bootstrap admin / first member → administrator, else data_steward)",
    )
    args = parser.parse_args()

    email = args.email.strip().lower()
    if not _auth.is_valid_org_email(email):
        sys.exit(f"Invalid email {email!r} — must be in name@organization.domain format")
    if not args.password:
        sys.exit("Password is required")

    with session_scope() as session:
        user = user_repo.create_user(
            session,
            email,
            _auth.hash_password(args.password),
            args.name,
            args.dept,
        )
        membership = org_repo.ensure_membership(session, user, role=args.role)
        print(
            f"Created/updated user {email} "
            f"(id={user.id}, org={membership.organisation_id}, role={membership.role})"
        )


if __name__ == "__main__":
    main()
