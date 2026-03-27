-- =============================================================================
-- 003_hermes_functions.sql
-- Hermes Email System — Utility Functions
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Get cycle stats for the last N hours
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION hermes_cycle_stats(hours_back INT DEFAULT 24)
RETURNS TABLE (
    total_drafts BIGINT,
    pending_review BIGINT,
    auto_sent BIGINT,
    manually_sent BIGINT,
    flagged BIGINT,
    stale BIGINT
)
LANGUAGE sql
SECURITY DEFINER
STABLE
AS $$
    SELECT
        COUNT(*)                                              AS total_drafts,
        COUNT(*) FILTER (WHERE status = 'pending_review')     AS pending_review,
        COUNT(*) FILTER (WHERE status = 'auto_sent')          AS auto_sent,
        COUNT(*) FILTER (WHERE status = 'sent')               AS manually_sent,
        COUNT(*) FILTER (WHERE flags::text != '[]')           AS flagged,
        COUNT(*) FILTER (WHERE status = 'stale')              AS stale
    FROM hermes_drafts
    WHERE created_at >= now() - (hours_back || ' hours')::interval;
$$;

-- ---------------------------------------------------------------------------
-- Purge old audit logs (keep last N days)
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION hermes_purge_audit_log(keep_days INT DEFAULT 180)
RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_count INT;
BEGIN
    DELETE FROM hermes_audit_log
    WHERE created_at < now() - (keep_days || ' days')::interval;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$;
