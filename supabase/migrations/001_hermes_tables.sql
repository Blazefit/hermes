-- =============================================================================
-- 001_hermes_tables.sql
-- Hermes Email System -- Core Schema (Generic)
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Enums (universal status/action types only -- categories are TEXT)
-- ---------------------------------------------------------------------------

DO $$ BEGIN
    CREATE TYPE hermes_draft_status AS ENUM (
        'pending_review',
        'approved',
        'sent',
        'auto_sent',
        'discarded',
        'stale'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
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
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS hermes_templates (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category            TEXT NOT NULL UNIQUE,
    anchor_text         TEXT NOT NULL,
    voice_samples       JSONB NOT NULL DEFAULT '[]',
    brand_voice_hash    TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hermes_drafts (
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

CREATE TABLE IF NOT EXISTS hermes_config (
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

CREATE TABLE IF NOT EXISTS hermes_audit_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id    UUID REFERENCES hermes_drafts (id) ON DELETE SET NULL,
    action      hermes_audit_action NOT NULL,
    actor       TEXT NOT NULL DEFAULT 'system',
    details     JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hermes_sender_history (
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

CREATE INDEX IF NOT EXISTS idx_hermes_drafts_status      ON hermes_drafts (status);
CREATE INDEX IF NOT EXISTS idx_hermes_drafts_category    ON hermes_drafts (category);
CREATE INDEX IF NOT EXISTS idx_hermes_drafts_created_at  ON hermes_drafts (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hermes_audit_created_at   ON hermes_audit_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hermes_sender_email       ON hermes_sender_history (email);

-- ---------------------------------------------------------------------------
-- Trigger Function: updated_at
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

DROP TRIGGER IF EXISTS trg_hermes_templates_updated_at ON hermes_templates;
CREATE TRIGGER trg_hermes_templates_updated_at
    BEFORE UPDATE ON hermes_templates
    FOR EACH ROW EXECUTE FUNCTION hermes_update_timestamp();

DROP TRIGGER IF EXISTS trg_hermes_config_updated_at ON hermes_config;
CREATE TRIGGER trg_hermes_config_updated_at
    BEFORE UPDATE ON hermes_config
    FOR EACH ROW EXECUTE FUNCTION hermes_update_timestamp();

DROP TRIGGER IF EXISTS trg_hermes_sender_history_updated_at ON hermes_sender_history;
CREATE TRIGGER trg_hermes_sender_history_updated_at
    BEFORE UPDATE ON hermes_sender_history
    FOR EACH ROW EXECUTE FUNCTION hermes_update_timestamp();
