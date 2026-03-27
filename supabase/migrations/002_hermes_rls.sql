-- =============================================================================
-- 002_hermes_rls.sql
-- Hermes Email System — Row Level Security
-- Single-user system: permissive policies for the authenticated role.
-- =============================================================================

-- hermes_templates
ALTER TABLE hermes_templates ENABLE ROW LEVEL SECURITY;
CREATE POLICY hermes_templates_authenticated_all
    ON hermes_templates AS PERMISSIVE FOR ALL TO authenticated
    USING (true) WITH CHECK (true);

-- hermes_drafts
ALTER TABLE hermes_drafts ENABLE ROW LEVEL SECURITY;
CREATE POLICY hermes_drafts_authenticated_all
    ON hermes_drafts AS PERMISSIVE FOR ALL TO authenticated
    USING (true) WITH CHECK (true);

-- hermes_config
ALTER TABLE hermes_config ENABLE ROW LEVEL SECURITY;
CREATE POLICY hermes_config_authenticated_all
    ON hermes_config AS PERMISSIVE FOR ALL TO authenticated
    USING (true) WITH CHECK (true);

-- hermes_audit_log
ALTER TABLE hermes_audit_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY hermes_audit_log_authenticated_all
    ON hermes_audit_log AS PERMISSIVE FOR ALL TO authenticated
    USING (true) WITH CHECK (true);

-- hermes_sender_history
ALTER TABLE hermes_sender_history ENABLE ROW LEVEL SECURITY;
CREATE POLICY hermes_sender_history_authenticated_all
    ON hermes_sender_history AS PERMISSIVE FOR ALL TO authenticated
    USING (true) WITH CHECK (true);
