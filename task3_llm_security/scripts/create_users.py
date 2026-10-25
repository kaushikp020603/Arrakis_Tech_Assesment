"""Create data/users.json (name -> scrypt hash) from demo/credentials.json.

    python scripts/create_users.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import settings  # noqa: E402
from app.security.auth import hash_password  # noqa: E402


def main():
    creds = json.loads(settings.CREDENTIALS_FILE.read_text(encoding="utf-8"))
    users = {u["name"].lower(): hash_password(u["password"]) for u in creds["valid_users"]}
    settings.USERS_FILE.parent.mkdir(exist_ok=True)
    settings.USERS_FILE.write_text(json.dumps(users, indent=2), encoding="utf-8")
    print(f"Wrote {len(users)} users with scrypt-hashed passwords to {settings.USERS_FILE}: {', '.join(users)}")


if __name__ == "__main__":
    main()
