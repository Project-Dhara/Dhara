"""
Admin CLI to provision a DHARA login. There is no public signup endpoint —
accounts are created here, by whoever holds DATABASE_URL.

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

from core import auth as _auth
from catalogue import catalogue as _cat


def main():
    parser = argparse.ArgumentParser(description="Create or update a DHARA login.")
    parser.add_argument("email", help="Login email, e.g. name@organization.domain")
    parser.add_argument("password")
    parser.add_argument("--name", default=None)
    parser.add_argument("--dept", default=None)
    args = parser.parse_args()

    email = args.email.strip().lower()
    if not _auth.is_valid_org_email(email):
        sys.exit(f"Invalid email {email!r} — must be in name@organization.domain format")
    if not args.password:
        sys.exit("Password is required")

    conn = _cat.get_connection()
    _cat.init_schema(conn)
    _cat.create_user(conn, email, _auth.hash_password(args.password), args.name, args.dept)
    conn.close()
    print(f"Created/updated user {email}")


if __name__ == "__main__":
    main()
