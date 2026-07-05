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
