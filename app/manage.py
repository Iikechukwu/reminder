"""Admin CLI for API keys (uses the DIRECT Neon URL).

    python -m app.manage create-key NAME
    python -m app.manage list-keys
    python -m app.manage revoke-key ID
"""
import sys

import psycopg
from psycopg.rows import dict_row

from app.auth import generate_key, hash_key
from app.config import Settings


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in {"create-key", "list-keys", "revoke-key"}:
        print(__doc__)
        return 2
    with psycopg.connect(Settings().database_url_direct, row_factory=dict_row) as conn:
        if argv[0] == "create-key" and len(argv) == 2:
            key = generate_key()
            conn.execute(
                "INSERT INTO api_keys (name, key_hash) VALUES (%s, %s)", (argv[1], hash_key(key))
            )
            print("API key (shown ONCE, store it now):")
            print(key)
        elif argv[0] == "list-keys":
            for r in conn.execute("SELECT id, name, created_at, revoked_at FROM api_keys ORDER BY id"):
                state = "revoked" if r["revoked_at"] else "active"
                print(f'{r["id"]:>4}  {r["name"]:<20} {state:<8} created {r["created_at"]:%Y-%m-%d}')
        elif argv[0] == "revoke-key" and len(argv) == 2:
            cur = conn.execute(
                "UPDATE api_keys SET revoked_at = now() WHERE id = %s AND revoked_at IS NULL",
                (int(argv[1]),),
            )
            print("revoked" if cur.rowcount else "no active key with that id")
        else:
            print(__doc__)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
