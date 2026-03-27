-- =============================================================================
-- 001_hermes_tables.sql
-- Hermes Email System — Core Schema (Generic)
-- Categories use TEXT instead of ENUM for user-defined flexibility.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Enums (status and action only — categories are free-form TEXT)
-- ---------------------------------------------------------------------------

CREATE TYPE hermes_draft_status AS ENUM (
    'pending_review',
    'approved',
    'sent',
    'auto_sent',
    'discarded',
    'stale'
);

CREATE TYPE hermes_audit_action AS ENUM (
    'generated',
    'regenerated',
    'edited',
    'sent',
    'auto_sent',
    'discarded',
    'fetch_failed',
    'cycle_skipped'
);

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------

CREATE TABLE hermes_templates (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category            TEXT NOT NULL UNIQUE,
    anchor_text         TEXT NOT NULL,
    voice_samples       JSONB NOT NULL DEFAULT '[]',
    brand_voice_hash    TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE hermes_drafts (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    gmail_account               TEXT NOT NULL,
    gmail_message_id            TEXT NOT NULL,
    gmail_thread_id             TEXT,
    sender_email                TEXT NOT NULL,
    sender_name                 TEXT,
    subject                     TEXT,
    original_body               TEXT NOT NULL,
    category                    TEXT NOT NULL DEFAULT 'uncategorized',
    classification_confidence   FLOAT,
    extracted_details           JSONB NOT NULL DEFAULT '{}',
    draft_text                  TEXT,
    generation_context          JSONB,
    flags                       JSONB NOT NULL DEFAULT '[]',
    status                      hermes_draft_status NOT NULL DEFAULT 'pending_review',
    model_used                  TEXT,
    user_edits                  TEXT,
    edit_diff                   JSONB,
    regeneration_count          INT NOT NULL DEFAULT 0,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at                     TIMESTAMPTZ,
    UNIQUE (gmail_message_id, gmail_account)
);

CREATE TABLE hermes_config (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category                    TEXT NOT NULL UNIQUE,
    auto_send_enabled           BOOLEAN NOT NULL DEFAULT false,
    auto_send_locked            BOOLEAN NOT NULL DEFAULT false,
    min_confidence_for_auto     FLOAT NOT NULL DEFAULT 0.9,
    reply_from_account          TEXT NOT NULL DEFAULT '',
    last_processed_at           TIMESTAMPTZ,
    last_trained_at             TIMESTAMPTZ,
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE hermes_audit_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id    UUID REFERENCES hermes_drafts (id) ON DELETE SET NULL,
    action      hermes_audit_action NOT NULL,
    actor       TEXT NOT NULL DEFAULT 'system',
    details     JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE hermes_sender_history (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email               TEXT NOT NULL UNIQUE,
    name                TEXT,
    first_contact       TIMESTAMPTZ NOT NULL DEFAULT now(),
    total_interactions  INT NOT NULL DEFAULT 1,
    categories          JSONB NOT NULL DEFAULT '[]',
    is_member           BOOLEAN NOT NULL DEFAULT false,
    notes               TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

CREATE INDEX idx_hermes_drafts_status      ON hermes_drafts (status);
CREATE INDEX idx_hermes_drafts_category    ON hermes_drafts (category);
CREATE INDEX idx_hermes_drafts_created_at  ON hermes_drafts (created_at DESC);
CREATE INDEX idx_hermes_audit_created_at   ON hermes_audit_log (created_at DESC);
CREATE INDEX idx_hermes_sender_email       ON hermes_sender_history (email);

-- ---------------------------------------------------------------------------
-- Trigger: auto-update updated_at
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION hermes_update_timestamp()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_hermes_templates_updated_at
    BEFORE UPDATE ON hermes_templates
    FOR EACH ROW EXECUTE FUNCTION hermes_update_timestamp();

CREATE TRIGGER trg_hermes_config_updated_at
    BEFORE UPDATE ON hermes_config
    FOR EACH ROW EXECUTE FUNCTION hermes_update_timestamp();

CREATE TRIGGER trg_hermes_sender_history_updated_at
    BEFORE UPDATE ON hermes_sender_history
    FOR EACH ROW EXECUTE FUNCTION hermes_update_timestamp();

-- ---------------------------------------------------------------------------
-- Advisory Lock Helpers
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION hermes_try_lock()
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
AS $$
    SELECT pg_try_advisory_lock(hashtext('hermes_email_cycle'));
$$;

CREATE OR REPLACE FUNCTION hermes_unlock()
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
AS $$
    SELECT pg_advisory_unlock(hashtext('hermes_email_cycle'));
$$;

-- ---------------------------------------------------------------------------
-- Maintenance: Archive old drafts (strip generation_context after 90 days)
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION hermes_archive_old_drafts()
RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_count INT;
BEGIN
    UPDATE hermes_drafts
    SET    generation_context = NULL
    WHERE  status IN ('sent', 'auto_sent', 'discarded', 'stale')
      AND  created_at < now() - INTERVAL '90 days'
      AND  generation_context IS NOT NULL;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$;
