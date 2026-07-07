CREATE TABLE IF NOT EXISTS vendor_rate_rules (
    id BIGSERIAL PRIMARY KEY,
    rule_id TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL,
    origin_warehouse TEXT,
    vendor_name TEXT,
    province TEXT,
    city TEXT,
    fsa TEXT,
    postal_code TEXT,
    address_fingerprint TEXT,
    pallet_min INTEGER NOT NULL,
    pallet_max INTEGER NOT NULL,
    weight_min_kg NUMERIC(12, 2),
    weight_max_kg NUMERIC(12, 2),
    base_cost_cad NUMERIC(12, 2) NOT NULL,
    fuel_percent NUMERIC(7, 4) NOT NULL DEFAULT 0,
    appointment_fee_cad NUMERIC(12, 2) NOT NULL DEFAULT 0,
    liftgate_fee_cad NUMERIC(12, 2) NOT NULL DEFAULT 0,
    residential_fee_cad NUMERIC(12, 2) NOT NULL DEFAULT 0,
    limited_access_fee_cad NUMERIC(12, 2) NOT NULL DEFAULT 0,
    remote_fee_cad NUMERIC(12, 2) NOT NULL DEFAULT 0,
    effective_from DATE,
    effective_to DATE,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_vendor_rate_rules_lookup
    ON vendor_rate_rules (source_type, province, city, fsa, postal_code, status);

CREATE TABLE IF NOT EXISTS quote_audit_log (
    id BIGSERIAL PRIMARY KEY,
    quote_id UUID NOT NULL,
    source_type TEXT NOT NULL,
    matched_rule TEXT NOT NULL,
    confidence INTEGER NOT NULL,
    internal_cost_cad NUMERIC(12, 2),
    suggested_selling_price_cad NUMERIC(12, 2),
    manual_review_required BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS postal_code_city_lookup (
    postal_code VARCHAR(10) PRIMARY KEY,
    preferred_city VARCHAR(100) NOT NULL,
    province VARCHAR(10),
    fsa VARCHAR(3),
    official_city VARCHAR(100),
    municipality VARCHAR(100),
    latitude NUMERIC(10, 6),
    longitude NUMERIC(10, 6),
    source TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_postal_code_city_lookup_province
    ON postal_code_city_lookup (province);

CREATE INDEX IF NOT EXISTS idx_postal_code_city_lookup_fsa
    ON postal_code_city_lookup (fsa);

CREATE TABLE IF NOT EXISTS zone_lookup_rules (
    id BIGSERIAL PRIMARY KEY,
    postal_prefix VARCHAR(3) NOT NULL,
    city VARCHAR(100) NOT NULL,
    province VARCHAR(10) NOT NULL,
    origin VARCHAR(32) NOT NULL,
    zone INTEGER NOT NULL,
    canonical_city VARCHAR(100),
    priority INTEGER NOT NULL DEFAULT 100,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    match_level VARCHAR(32),
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_zone_lookup_rules_lookup
    ON zone_lookup_rules (postal_prefix, province, city, canonical_city, active, priority);

CREATE TABLE IF NOT EXISTS postal_zone_overrides (
    id BIGSERIAL PRIMARY KEY,
    postal_code VARCHAR(10) NOT NULL UNIQUE,
    postal_prefix VARCHAR(3) NOT NULL,
    province VARCHAR(10) NOT NULL,
    canonical_city VARCHAR(100),
    origin VARCHAR(32) NOT NULL,
    zone INTEGER NOT NULL,
    confidence INTEGER NOT NULL DEFAULT 100,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    source TEXT,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_postal_zone_overrides_lookup
    ON postal_zone_overrides (postal_code, postal_prefix, province, canonical_city, active);

CREATE TABLE IF NOT EXISTS city_aliases (
    id BIGSERIAL PRIMARY KEY,
    province VARCHAR(10) NOT NULL,
    alias_city VARCHAR(100) NOT NULL,
    canonical_city VARCHAR(100) NOT NULL,
    alias_type VARCHAR(32),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    source TEXT,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_city_aliases_province_alias UNIQUE (province, alias_city)
);

CREATE INDEX IF NOT EXISTS idx_city_aliases_lookup
    ON city_aliases (province, alias_city, canonical_city, active);

CREATE TABLE IF NOT EXISTS zone_price_matrix (
    id BIGSERIAL PRIMARY KEY,
    origin VARCHAR(32) NOT NULL,
    zone INTEGER NOT NULL,
    billing_pallets INTEGER NOT NULL,
    base_price_usd NUMERIC(12, 2) NOT NULL,
    source TEXT,
    last_updated VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_zone_price_matrix_lookup UNIQUE (origin, zone, billing_pallets)
);

CREATE INDEX IF NOT EXISTS idx_zone_price_matrix_lookup
    ON zone_price_matrix (origin, zone, billing_pallets);

CREATE TABLE IF NOT EXISTS quote_rule_config (
    key VARCHAR(128) PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS quote_audit_logs (
    id BIGSERIAL PRIMARY KEY,
    quote_id VARCHAR(64) NOT NULL,
    request_json JSONB NOT NULL,
    result_json JSONB NOT NULL,
    source_type VARCHAR(64) NOT NULL,
    postal_code VARCHAR(10),
    postal_prefix VARCHAR(3),
    city VARCHAR(100),
    province VARCHAR(10),
    origin VARCHAR(32),
    zone INTEGER,
    billing_pallets INTEGER,
    base_price_usd NUMERIC(12, 2),
    total_price_usd NUMERIC(12, 2),
    manual_review_required BOOLEAN NOT NULL,
    risk_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quote_audit_logs_quote_id
    ON quote_audit_logs (quote_id);

CREATE INDEX IF NOT EXISTS idx_quote_audit_logs_lookup
    ON quote_audit_logs (source_type, postal_prefix, province, origin, zone, manual_review_required);

CREATE TABLE IF NOT EXISTS manual_quote_tasks (
    id BIGSERIAL PRIMARY KEY,
    quote_id VARCHAR(64) NOT NULL,
    reason TEXT NOT NULL,
    risk_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    request_json JSONB NOT NULL,
    result_json JSONB NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    assigned_to VARCHAR(128),
    resolved_price_usd NUMERIC(12, 2),
    resolved_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_manual_quote_tasks_status
    ON manual_quote_tasks (status, created_at);

CREATE INDEX IF NOT EXISTS idx_manual_quote_tasks_quote_id
    ON manual_quote_tasks (quote_id);

CREATE TABLE IF NOT EXISTS learned_quote_rules (
    id BIGSERIAL PRIMARY KEY,
    source_task_id INTEGER,
    quote_id VARCHAR(64),
    scope VARCHAR(32) NOT NULL,
    postal_code VARCHAR(10),
    postal_prefix VARCHAR(3),
    city VARCHAR(100),
    province VARCHAR(10),
    origin VARCHAR(32),
    zone INTEGER,
    billing_pallets INTEGER NOT NULL,
    total_price_usd NUMERIC(12, 2) NOT NULL,
    base_price_usd NUMERIC(12, 2),
    confidence INTEGER NOT NULL DEFAULT 60,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    usage_count INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_learned_quote_rules_lookup
    ON learned_quote_rules (status, billing_pallets, postal_prefix, city, province);

CREATE INDEX IF NOT EXISTS idx_learned_quote_rules_quote_id
    ON learned_quote_rules (quote_id);

CREATE TABLE IF NOT EXISTS hermes_learning_candidates (
    id BIGSERIAL PRIMARY KEY,
    source_task_id INTEGER,
    quote_id VARCHAR(64),
    candidate_type VARCHAR(64) NOT NULL DEFAULT 'learned_exception_price',
    scope VARCHAR(32) NOT NULL,
    postal_code VARCHAR(10),
    postal_prefix VARCHAR(3),
    city VARCHAR(100),
    province VARCHAR(10),
    origin VARCHAR(32),
    zone INTEGER,
    billing_pallets INTEGER NOT NULL,
    resolved_total_price_usd NUMERIC(12, 2) NOT NULL,
    resolved_base_price_usd NUMERIC(12, 2),
    confidence INTEGER NOT NULL DEFAULT 60,
    support_count INTEGER NOT NULL DEFAULT 1,
    status VARCHAR(32) NOT NULL DEFAULT 'pending_review',
    duplicate_key VARCHAR(255) NOT NULL,
    proposal_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    risk_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    review_note TEXT,
    reviewed_by VARCHAR(128),
    reviewed_at TIMESTAMPTZ,
    promoted_rule_id INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_hermes_learning_candidates_status
    ON hermes_learning_candidates (status, updated_at);

CREATE INDEX IF NOT EXISTS idx_hermes_learning_candidates_lookup
    ON hermes_learning_candidates (postal_prefix, city, province, billing_pallets);

CREATE INDEX IF NOT EXISTS idx_hermes_learning_candidates_duplicate_key
    ON hermes_learning_candidates (duplicate_key);

CREATE TABLE IF NOT EXISTS ai_model_configs (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    provider VARCHAR(32) NOT NULL DEFAULT 'openai',
    base_url TEXT,
    api_key_encrypted TEXT,
    model_name VARCHAR(128) NOT NULL,
    temperature DOUBLE PRECISION NOT NULL DEFAULT 0,
    max_tokens INTEGER NOT NULL DEFAULT 800,
    timeout_seconds INTEGER NOT NULL DEFAULT 30,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    purpose VARCHAR(32) NOT NULL DEFAULT 'general',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ai_model_configs_default
    ON ai_model_configs (is_default, enabled);

CREATE INDEX IF NOT EXISTS idx_ai_model_configs_purpose
    ON ai_model_configs (purpose, enabled);

CREATE TABLE IF NOT EXISTS wecom_bot_configs (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    webhook_url_encrypted TEXT,
    bot_id VARCHAR(128),
    secret_encrypted TEXT,
    bot_type VARCHAR(32) NOT NULL DEFAULT 'group_webhook',
    purpose VARCHAR(32) NOT NULL DEFAULT 'general',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    mention_all_on_manual_required BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_wecom_bot_configs_default
    ON wecom_bot_configs (is_default, enabled);

CREATE INDEX IF NOT EXISTS idx_wecom_bot_configs_purpose
    ON wecom_bot_configs (purpose, enabled);

CREATE TABLE IF NOT EXISTS email_notification_configs (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    smtp_host VARCHAR(255) NOT NULL,
    smtp_port INTEGER NOT NULL DEFAULT 587,
    username VARCHAR(255),
    password_encrypted TEXT,
    from_email VARCHAR(255) NOT NULL,
    from_name VARCHAR(128),
    recipient_emails JSONB NOT NULL,
    use_tls BOOLEAN NOT NULL DEFAULT TRUE,
    use_ssl BOOLEAN NOT NULL DEFAULT FALSE,
    purpose VARCHAR(32) NOT NULL DEFAULT 'general',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_email_notification_configs_default
    ON email_notification_configs (is_default, enabled);

CREATE INDEX IF NOT EXISTS idx_email_notification_configs_purpose
    ON email_notification_configs (purpose, enabled);

CREATE TABLE IF NOT EXISTS search_api_configs (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    provider VARCHAR(32) NOT NULL DEFAULT 'tavily',
    base_url TEXT,
    api_key_encrypted TEXT NOT NULL,
    purpose VARCHAR(32) NOT NULL DEFAULT 'general',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_search_api_configs_default
    ON search_api_configs (is_default, enabled);

CREATE INDEX IF NOT EXISTS idx_search_api_configs_purpose
    ON search_api_configs (purpose, enabled);

CREATE TABLE IF NOT EXISTS api_keys (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    key_hash VARCHAR(128) NOT NULL UNIQUE,
    role VARCHAR(32) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_api_keys_hash
    ON api_keys (key_hash);

CREATE INDEX IF NOT EXISTS idx_api_keys_role
    ON api_keys (role);

CREATE INDEX IF NOT EXISTS idx_api_keys_enabled
    ON api_keys (enabled);
