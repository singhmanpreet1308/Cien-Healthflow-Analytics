"""Create or update CienMed AI login accounts (passwords stored as bcrypt hashes).

Usage:
  python manage_users.py add <username> <role: clinician|admin> "<Display Name>"   (prompts for password)
  python manage_users.py demo        # creates demo accounts dr.demo / admin.demo
  python manage_users.py guest       # creates cache-only guest accounts (safe to share publicly)
  python manage_users.py list

Trial accounts (expire after N days, limited daily AI calls):
  python manage_users.py requests                          # open in-app access requests (GitHub issues)
  python manage_users.py approve <request#> [days]         # create a trial account from a request
  python manage_users.py reject <request#> "<reason>"      # close a request without an account
  python manage_users.py trial <email> <role> "<Name>" [days]   # e.g. for Google Form requests
  python manage_users.py extend <username> <days>          # new expiry = today + days
  python manage_users.py limit <username> <calls/day>      # change the daily AI-call limit
"""
import getpass
import re
import secrets
import sys
from datetime import date, timedelta

import yaml

from cienmed import access, config
from cienmed.governance import hash_password, load_users

TRIAL_DAYS = 7
TRIAL_DAILY_LIMIT = 20
ROLES = ("clinician", "admin")


def save(users: dict) -> None:
    config.USERS_FILE.write_text(yaml.safe_dump({"users": users}, sort_keys=True))


def _expiry(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _username_for(email: str, users: dict) -> str:
    """jo.smith@acme.com -> jo.smith (jo.smith2, ... if taken by someone else)."""
    base = re.sub(r"[^a-z0-9._-]", "", email.split("@")[0].lower()) or "user"
    name, n = base, 2
    while name in users and users[name].get("email") != email.lower():
        name, n = f"{base}{n}", n + 1
    return name


def create_trial(users: dict, email: str, role: str, name: str, days: int) -> tuple[str, str]:
    """Add/refresh a trial account. Returns (username, plain password) — the password is only printed."""
    username = _username_for(email, users)
    password = secrets.token_urlsafe(9)
    users[username] = {"name": name, "role": role, "email": email.lower(), "password_hash": hash_password(password),
                       "expires": _expiry(days), "daily_limit": TRIAL_DAILY_LIMIT}
    save(users)
    return username, password


def _print_credentials(username: str, users: dict, password: str) -> None:
    u = users[username]
    print(f"Created trial account ({u['role']}), valid until {u['expires']}, {u['daily_limit']} AI calls/day.")
    print(f"Username: {username}")
    print(f"Password: {password}")
    print("Send these to the requester privately (e.g. by email). They are not stored anywhere in plain text.")


def main(argv):
    users = load_users()
    cmd, args = (argv[0], argv[1:]) if argv else ("list", [])
    try:
        if cmd == "list":
            for u, d in users.items():
                extra = f"  expires {d['expires']}" if d.get("expires") else ""
                extra += f"  limit {d['daily_limit']}/day" if d.get("daily_limit") is not None else ""
                print(f"{u:20s} {d['role']:10s} {d['name']}{extra}")
        elif cmd == "demo":
            users["dr.demo"] = {"name": "Dr Demo (Clinician)", "role": "clinician", "password_hash": hash_password("Clinician@123")}
            users["admin.demo"] = {"name": "Admin Demo (Operations)", "role": "admin", "password_hash": hash_password("Admin@123")}
            save(users)
            print("Demo users created: dr.demo / Clinician@123, admin.demo / Admin@123 — change these before sharing.")
        elif cmd == "guest":
            # Public demo accounts: cache-only (see CIENMED_CACHE_ONLY_USERS), safe to share
            users["guest.clinician"] = {"name": "Guest (Clinician demo)", "role": "clinician",
                                        "password_hash": hash_password("CienDemo@2026")}
            users["guest.admin"] = {"name": "Guest (Admin demo)", "role": "admin",
                                    "password_hash": hash_password("CienDemo@2026")}
            save(users)
            print("Guest users created: guest.clinician / guest.admin, password CienDemo@2026 (example questions only).")
        elif cmd == "add" and len(args) == 3 and args[1] in ROLES:
            pw = getpass.getpass("Password: ")
            users[args[0].lower()] = {"name": args[2], "role": args[1], "password_hash": hash_password(pw)}
            save(users)
            print(f"Saved {args[0]} ({args[1]})")
        elif cmd == "requests":
            reqs = access.open_requests()
            for r in reqs:
                print(f"#{r['number']:<4} {r['created']}  {r['role']:9s} {r['name']} <{r['email']}>  "
                      f"{r['org']} — {r['reason']}")
            if not reqs:
                print("No open access requests.")
        elif cmd == "approve" and 1 <= len(args) <= 2:
            number, days = int(args[0]), int(args[1]) if len(args) == 2 else TRIAL_DAYS
            req = access.get_request(number)
            if req["role"] not in ROLES:
                raise access.AccessError(f"#{number} has an unknown role '{req['role']}'.")
            username, password = create_trial(users, req["email"], req["role"], req["name"], days)
            access.close_request(number, access.LABEL_APPROVED,
                                 f"Approved: trial account `{username}` ({req['role']}) valid until "
                                 f"{users[username]['expires']}. Credentials sent to the requester separately.")
            _print_credentials(username, users, password)
            print(f"Request #{number} closed as approved.")
        elif cmd == "reject" and 1 <= len(args) <= 2:
            number = int(args[0])
            access.get_request(number)          # checks it is an open access request
            reason = args[1] if len(args) == 2 else "No reason given."
            access.close_request(number, access.LABEL_REJECTED, f"Rejected: {reason}")
            print(f"Request #{number} closed as rejected.")
        elif cmd == "trial" and 3 <= len(args) <= 4 and args[1] in ROLES:
            if not access.EMAIL_RE.match(args[0]):
                raise access.AccessError(f"'{args[0]}' is not a valid email address.")
            days = int(args[3]) if len(args) == 4 else TRIAL_DAYS
            username, password = create_trial(users, args[0], args[1], args[2], days)
            _print_credentials(username, users, password)
        elif cmd == "extend" and len(args) == 2:
            user = users.get(args[0].lower())
            if not user:
                raise access.AccessError(f"No account '{args[0]}'.")
            user["expires"] = _expiry(int(args[1]))
            save(users)
            print(f"{args[0]} now valid until {user['expires']}.")
        elif cmd == "limit" and len(args) == 2:
            user = users.get(args[0].lower())
            if not user:
                raise access.AccessError(f"No account '{args[0]}'.")
            user["daily_limit"] = int(args[1])
            save(users)
            print(f"{args[0]} can now make {user['daily_limit']} AI calls/day.")
        else:
            print(__doc__)
    except (access.AccessError, ValueError) as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
