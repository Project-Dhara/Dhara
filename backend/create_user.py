"""
Admin CLI to provision a DHARA login. There is no public signup endpoint —
accounts are created here, by whoever holds DATABASE_URL.

Usage:
    python create_user.py aparajita@peopleplus.ai 'some-password' --name "Aparajita" --dept "DES"
"""

import argparse
import sys

from dotenv import load_dotenv

load_dotenv()

import auth as _auth
import catalogue as _cat


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
