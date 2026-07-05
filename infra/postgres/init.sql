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
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_postal_code_city_lookup_province
    ON postal_code_city_lookup (province);

CREATE TABLE IF NOT EXISTS zone_lookup_rules (
    id BIGSERIAL PRIMARY KEY,
    postal_prefix VARCHAR(3) NOT NULL,
    city VARCHAR(100) NOT NULL,
    province VARCHAR(10) NOT NULL,
    origin VARCHAR(32) NOT NULL,
    zone INTEGER NOT NULL,
    match_level VARCHAR(32),
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_zone_lookup_rules_lookup
    ON zone_lookup_rules (postal_prefix, province, city);

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
