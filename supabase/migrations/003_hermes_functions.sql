-- =============================================================================
-- 003_hermes_functions.sql
-- Hermes Email System -- Advisory Lock & Maintenance Functions
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Advisory Lock Helpers
-- Used to ensure only one processing cycle runs at a time.
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
-- Maintenance: Archive old drafts
-- Strips generation_context from drafts older than 90 days that are in a
-- terminal status (sent, auto_sent, discarded, stale). Returns row count.
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
