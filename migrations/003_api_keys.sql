-- API keys are stored HASHED (SHA-256). The plaintext key is shown once, when
-- created, and cannot be recovered from the database.
CREATE TABLE api_keys (
    id         bigserial PRIMARY KEY,
    name       text NOT NULL,
    key_hash   text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz
);
