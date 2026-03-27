-- =============================================================================
-- 004_hermes_blacklist.sql
-- Hermes Email System — Sender Blacklist
-- Auto-discard emails from known non-customer senders.
-- =============================================================================

CREATE TABLE hermes_sender_blacklist (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT NOT NULL,
    domain      TEXT,
    reason      TEXT DEFAULT 'Not relevant',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX idx_hermes_blacklist_email ON hermes_sender_blacklist (email);
CREATE INDEX idx_hermes_blacklist_domain ON hermes_sender_blacklist (domain);

ALTER TABLE hermes_sender_blacklist ENABLE ROW LEVEL SECURITY;
CREATE POLICY hermes_blacklist_all
    ON hermes_sender_blacklist AS PERMISSIVE FOR ALL TO authenticated
    USING (true) WITH CHECK (true);
