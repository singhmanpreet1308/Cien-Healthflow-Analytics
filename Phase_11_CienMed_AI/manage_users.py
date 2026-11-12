"""Create or update CienMed AI login accounts (passwords stored as bcrypt hashes).

Usage:
  python manage_users.py add <username> <role: clinician|admin> "<Display Name>"   (prompts for password)
  python manage_users.py demo        # creates demo accounts dr.demo / admin.demo
  python manage_users.py guest       # creates cache-only guest accounts (safe to share publicly)
  python manage_users.py list
"""
import getpass
import sys

import yaml

from cienmed import config
from cienmed.governance import hash_password, load_users


def save(users: dict) -> None:
    config.USERS_FILE.write_text(yaml.safe_dump({"users": users}, sort_keys=True))


def main(argv):
    users = load_users()
    if not argv or argv[0] == "list":
        for u, d in users.items():
            print(f"{u:20s} {d['role']:10s} {d['name']}")
    elif argv[0] == "demo":
        users["dr.demo"] = {"name": "Dr Demo (Clinician)", "role": "clinician", "password_hash": hash_password("Clinician@123")}
        users["admin.demo"] = {"name": "Admin Demo (Operations)", "role": "admin", "password_hash": hash_password("Admin@123")}
        save(users)
        print("Demo users created: dr.demo / Clinician@123, admin.demo / Admin@123 — change these before sharing.")
    elif argv[0] == "guest":
        # Public demo accounts: cache-only (see CIENMED_CACHE_ONLY_USERS), safe to share
        users["guest.clinician"] = {"name": "Guest (Clinician demo)", "role": "clinician",
                                    "password_hash": hash_password("CienDemo@2026")}
        users["guest.admin"] = {"name": "Guest (Admin demo)", "role": "admin",
                                "password_hash": hash_password("CienDemo@2026")}
        save(users)
        print("Guest users created: guest.clinician / guest.admin, password CienDemo@2026 (example questions only).")
    elif argv[0] == "add" and len(argv) == 4 and argv[2] in ("clinician", "admin"):
        pw = getpass.getpass("Password: ")
        users[argv[1].lower()] = {"name": argv[3], "role": argv[2], "password_hash": hash_password(pw)}
        save(users)
        print(f"Saved {argv[1]} ({argv[2]})")
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])