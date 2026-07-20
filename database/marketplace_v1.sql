-- Canada Logistics Marketplace
-- PostgreSQL architecture baseline v1.0
-- Date: 2026-07-17
-- This file is an architecture deliverable. The database implementation phase
-- will translate it into a reviewed Prisma schema and versioned migrations.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS marketplace;
SET search_path TO marketplace, public;

CREATE OR REPLACE FUNCTION marketplace.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION marketplace.reject_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$;

-- ---------------------------------------------------------------------------
-- Identity, organizations, sessions, and organization-scoped RBAC
-- ---------------------------------------------------------------------------

CREATE TABLE organizations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code text NOT NULL UNIQUE,
  display_name text NOT NULL,
  legal_name text,
  organization_type text NOT NULL
    CHECK (organization_type IN ('PLATFORM', 'CUSTOMER', 'SUPPLIER', 'BOTH')),
  status text NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('INVITED', 'ACTIVE', 'SUSPENDED', 'CLOSED')),
  default_currency char(3) NOT NULL DEFAULT 'CAD',
  timezone text NOT NULL DEFAULT 'America/Toronto',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CHECK (code ~ '^[A-Z0-9][A-Z0-9_-]{1,31}$'),
  CHECK (default_currency ~ '^[A-Z]{3}$')
);

CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text NOT NULL,
  display_name text NOT NULL,
  phone text,
  password_hash text,
  status text NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('PENDING', 'ACTIVE', 'LOCKED', 'DISABLED')),
  locale text NOT NULL DEFAULT 'en-CA',
  timezone text NOT NULL DEFAULT 'America/Toronto',
  email_verified_at timestamptz,
  last_login_at timestamptz,
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CHECK (position('@' IN email) > 1)
);

CREATE UNIQUE INDEX uq_users_email_ci ON users (lower(email)) WHERE deleted_at IS NULL;

CREATE TABLE organization_memberships (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  user_id uuid NOT NULL REFERENCES users(id),
  membership_type text NOT NULL DEFAULT 'EMPLOYEE'
    CHECK (membership_type IN ('OWNER', 'EMPLOYEE', 'CONTRACTOR', 'EXTERNAL')),
  status text NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('INVITED', 'ACTIVE', 'SUSPENDED', 'REMOVED')),
  title text,
  joined_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, user_id)
);

CREATE TABLE roles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_organization_id uuid REFERENCES organizations(id),
  code text NOT NULL,
  name text NOT NULL,
  scope text NOT NULL CHECK (scope IN ('PLATFORM', 'ORGANIZATION')),
  is_system boolean NOT NULL DEFAULT false,
  description text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (
    (scope = 'PLATFORM' AND owner_organization_id IS NULL) OR
    (scope = 'ORGANIZATION' AND owner_organization_id IS NOT NULL)
  )
);

CREATE UNIQUE INDEX uq_roles_platform_code
  ON roles (code) WHERE owner_organization_id IS NULL;
CREATE UNIQUE INDEX uq_roles_org_code
  ON roles (owner_organization_id, code) WHERE owner_organization_id IS NOT NULL;

CREATE TABLE permissions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code text NOT NULL UNIQUE,
  module text NOT NULL,
  action text NOT NULL,
  description text,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (code ~ '^[a-z0-9_.:-]+$')
);

CREATE TABLE role_permissions (
  role_id uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  permission_id uuid NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE membership_roles (
  membership_id uuid NOT NULL REFERENCES organization_memberships(id) ON DELETE CASCADE,
  role_id uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  assigned_by_user_id uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (membership_id, role_id)
);

CREATE TABLE auth_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  refresh_token_hash text NOT NULL UNIQUE,
  token_family_id uuid NOT NULL,
  ip_address inet,
  user_agent text,
  expires_at timestamptz NOT NULL,
  last_used_at timestamptz,
  revoked_at timestamptz,
  revoke_reason text,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (expires_at > created_at)
);

CREATE INDEX ix_auth_sessions_user_active
  ON auth_sessions (user_id, expires_at) WHERE revoked_at IS NULL;

CREATE TABLE invitations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  email text NOT NULL,
  role_id uuid REFERENCES roles(id),
  token_hash text NOT NULL UNIQUE,
  status text NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'ACCEPTED', 'EXPIRED', 'REVOKED')),
  invited_by_user_id uuid REFERENCES users(id),
  expires_at timestamptz NOT NULL,
  accepted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (expires_at > created_at)
);

CREATE INDEX ix_invitations_pending
  ON invitations (organization_id, lower(email), expires_at)
  WHERE status = 'PENDING';

CREATE TABLE api_clients (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  name text NOT NULL,
  client_id text NOT NULL UNIQUE,
  secret_hash text NOT NULL,
  scopes text[] NOT NULL DEFAULT ARRAY[]::text[],
  status text NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE', 'DISABLED', 'REVOKED')),
  expires_at timestamptz,
  last_used_at timestamptz,
  created_by_user_id uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Shared files, external connections, locations, and AI governance
-- ---------------------------------------------------------------------------

CREATE TABLE file_assets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid REFERENCES organizations(id),
  uploaded_by_user_id uuid REFERENCES users(id),
  purpose text NOT NULL,
  storage_bucket text NOT NULL,
  storage_key text NOT NULL,
  original_filename text,
  media_type text NOT NULL,
  byte_size bigint NOT NULL CHECK (byte_size >= 0),
  sha256 char(64) NOT NULL,
  encryption_key_ref text,
  malware_scan_status text NOT NULL DEFAULT 'PENDING'
    CHECK (malware_scan_status IN ('PENDING', 'CLEAN', 'INFECTED', 'FAILED')),
  retention_until timestamptz,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (storage_bucket, storage_key),
  CHECK (sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX ix_file_assets_org_created ON file_assets (organization_id, created_at DESC);

CREATE TABLE file_asset_links (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  file_asset_id uuid NOT NULL REFERENCES file_assets(id) ON DELETE CASCADE,
  entity_type text NOT NULL,
  entity_id uuid NOT NULL,
  purpose text NOT NULL,
  created_by_user_id uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (file_asset_id, entity_type, entity_id, purpose)
);

CREATE INDEX ix_file_asset_links_entity
  ON file_asset_links (entity_type, entity_id, purpose);

CREATE TABLE integration_connections (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid REFERENCES organizations(id),
  connection_type text NOT NULL
    CHECK (connection_type IN ('EMAIL', 'API', 'WEBHOOK', 'EXCEL', 'RESEND', 'GOOGLE_MAPS', 'S3')),
  name text NOT NULL,
  status text NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('DRAFT', 'ACTIVE', 'ERROR', 'DISABLED')),
  encrypted_config text NOT NULL,
  config_key_ref text NOT NULL,
  capabilities text[] NOT NULL DEFAULT ARRAY[]::text[],
  last_verified_at timestamptz,
  last_error_code text,
  created_by_user_id uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, name)
);

CREATE TABLE locations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid REFERENCES organizations(id),
  location_type text NOT NULL DEFAULT 'ADDRESS'
    CHECK (location_type IN ('ADDRESS', 'PORT', 'AIRPORT', 'RAIL_RAMP', 'WAREHOUSE', 'CFS', 'CUSTOMS')),
  name text,
  contact_name text,
  contact_phone text,
  address_line1 text,
  address_line2 text,
  city text NOT NULL,
  province_state text,
  postal_code text,
  fsa text,
  country_code char(2) NOT NULL,
  latitude numeric(9,6),
  longitude numeric(9,6),
  timezone text,
  verification_status text NOT NULL DEFAULT 'UNVERIFIED'
    CHECK (verification_status IN ('UNVERIFIED', 'VERIFIED', 'FAILED', 'OVERRIDDEN')),
  normalized_hash char(64),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (country_code ~ '^[A-Z]{2}$'),
  CHECK (fsa IS NULL OR fsa ~ '^[A-Z][0-9][A-Z]$'),
  CHECK (latitude IS NULL OR latitude BETWEEN -90 AND 90),
  CHECK (longitude IS NULL OR longitude BETWEEN -180 AND 180)
);

CREATE INDEX ix_locations_postal ON locations (country_code, postal_code);
CREATE INDEX ix_locations_city ON locations (country_code, province_state, city);
CREATE INDEX ix_locations_fsa ON locations (fsa) WHERE fsa IS NOT NULL;

CREATE TABLE ai_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid REFERENCES organizations(id),
  purpose text NOT NULL
    CHECK (purpose IN ('PLAN_GENERATION', 'QUOTE_PARSE', 'PRICE_FORECAST', 'PRICE_RECOMMENDATION', 'EXPLANATION')),
  target_entity_type text NOT NULL,
  target_entity_id uuid NOT NULL,
  provider text NOT NULL,
  model_name text NOT NULL,
  model_version text,
  prompt_version text NOT NULL,
  input_schema_version text NOT NULL,
  output_schema_version text NOT NULL,
  input_hash char(64) NOT NULL,
  input_asset_id uuid REFERENCES file_assets(id),
  output_asset_id uuid REFERENCES file_assets(id),
  status text NOT NULL DEFAULT 'QUEUED'
    CHECK (status IN ('QUEUED', 'RUNNING', 'VALIDATED', 'REVIEW_REQUIRED', 'FAILED', 'CANCELLED')),
  validation_errors jsonb NOT NULL DEFAULT '[]'::jsonb,
  token_input_count integer CHECK (token_input_count IS NULL OR token_input_count >= 0),
  token_output_count integer CHECK (token_output_count IS NULL OR token_output_count >= 0),
  latency_ms integer CHECK (latency_ms IS NULL OR latency_ms >= 0),
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (input_hash ~ '^[0-9a-f]{64}$')
);

CREATE INDEX ix_ai_runs_target ON ai_runs (target_entity_type, target_entity_id, created_at DESC);
CREATE INDEX ix_ai_runs_status ON ai_runs (status, created_at);

CREATE TABLE ai_run_evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ai_run_id uuid NOT NULL REFERENCES ai_runs(id) ON DELETE CASCADE,
  evidence_key text NOT NULL,
  source_type text NOT NULL,
  source_entity_type text,
  source_entity_id uuid,
  source_asset_id uuid REFERENCES file_assets(id),
  content_hash char(64) NOT NULL,
  summary text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (ai_run_id, evidence_key),
  CHECK (content_hash ~ '^[0-9a-f]{64}$')
);

CREATE TABLE review_tasks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid REFERENCES organizations(id),
  module text NOT NULL,
  entity_type text NOT NULL,
  entity_id uuid NOT NULL,
  reason_code text NOT NULL,
  severity text NOT NULL DEFAULT 'MEDIUM'
    CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
  status text NOT NULL DEFAULT 'OPEN'
    CHECK (status IN ('OPEN', 'ASSIGNED', 'WAITING_EXTERNAL', 'RESOLVED', 'CANCELLED')),
  assigned_to_user_id uuid REFERENCES users(id),
  resolution_code text,
  resolution_note text,
  due_at timestamptz,
  resolved_at timestamptz,
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_review_tasks_queue
  ON review_tasks (status, severity, due_at) WHERE status IN ('OPEN', 'ASSIGNED', 'WAITING_EXTERNAL');

CREATE TABLE async_operations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid REFERENCES organizations(id),
  requested_by_user_id uuid REFERENCES users(id),
  requested_by_api_client_id uuid REFERENCES api_clients(id),
  operation_type text NOT NULL,
  target_entity_type text,
  target_entity_id uuid,
  status text NOT NULL DEFAULT 'QUEUED'
    CHECK (status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')),
  progress_percent numeric(5,2) NOT NULL DEFAULT 0
    CHECK (progress_percent BETWEEN 0 AND 100),
  result_entity_type text,
  result_entity_id uuid,
  result_payload jsonb,
  error_code text,
  error_detail text,
  started_at timestamptz,
  completed_at timestamptz,
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (expires_at > created_at),
  CHECK (requested_by_user_id IS NOT NULL OR requested_by_api_client_id IS NOT NULL)
);

CREATE INDEX ix_async_operations_requester
  ON async_operations (requested_by_user_id, created_at DESC)
  WHERE requested_by_user_id IS NOT NULL;
CREATE INDEX ix_async_operations_active
  ON async_operations (status, created_at) WHERE status IN ('QUEUED', 'RUNNING');

-- ---------------------------------------------------------------------------
-- Service Catalog and Supplier Center
-- ---------------------------------------------------------------------------

CREATE TABLE service_categories (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code text NOT NULL UNIQUE,
  name text NOT NULL,
  sort_order integer NOT NULL DEFAULT 0,
  status text NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE', 'INACTIVE')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE service_definitions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  category_id uuid NOT NULL REFERENCES service_categories(id),
  code text NOT NULL UNIQUE,
  name text NOT NULL,
  description text,
  service_kind text NOT NULL
    CHECK (service_kind IN ('TRANSPORT', 'PICKUP', 'CUSTOMS', 'WAREHOUSE', 'DELIVERY', 'VALUE_ADDED', 'TAX_IMPORT')),
  default_stage text NOT NULL
    CHECK (default_stage IN ('ORIGIN', 'MAIN_CARRIAGE', 'CANADA_IMPORT', 'WAREHOUSE', 'FINAL_MILE', 'VALUE_ADDED')),
  input_schema jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('DRAFT', 'ACTIVE', 'INACTIVE')),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  created_by_user_id uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);

CREATE INDEX ix_service_definitions_catalog
  ON service_definitions (category_id, status, name) WHERE deleted_at IS NULL;

CREATE TABLE service_relationships (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  from_service_id uuid NOT NULL REFERENCES service_definitions(id),
  to_service_id uuid NOT NULL REFERENCES service_definitions(id),
  relationship_type text NOT NULL
    CHECK (relationship_type IN ('REQUIRES', 'PRECEDES', 'EXCLUDES', 'ALTERNATIVE', 'CAN_FOLLOW')),
  condition_schema jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE', 'INACTIVE')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (from_service_id, to_service_id, relationship_type),
  CHECK (from_service_id <> to_service_id)
);

CREATE TABLE supplier_profiles (
  organization_id uuid PRIMARY KEY REFERENCES organizations(id),
  supplier_code text NOT NULL UNIQUE,
  onboarding_status text NOT NULL DEFAULT 'PENDING'
    CHECK (onboarding_status IN ('PENDING', 'UNDER_REVIEW', 'APPROVED', 'SUSPENDED', 'REJECTED')),
  payment_terms text,
  service_regions jsonb NOT NULL DEFAULT '[]'::jsonb,
  risk_level text NOT NULL DEFAULT 'STANDARD'
    CHECK (risk_level IN ('LOW', 'STANDARD', 'HIGH', 'BLOCKED')),
  approved_at timestamptz,
  approved_by_user_id uuid REFERENCES users(id),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE supplier_contacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  supplier_organization_id uuid NOT NULL REFERENCES supplier_profiles(organization_id),
  name text NOT NULL,
  email text,
  phone text,
  role_title text,
  is_primary boolean NOT NULL DEFAULT false,
  preferred_channels text[] NOT NULL DEFAULT ARRAY['EMAIL']::text[],
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_supplier_primary_contact
  ON supplier_contacts (supplier_organization_id) WHERE is_primary = true;

CREATE TABLE supplier_certifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  supplier_organization_id uuid NOT NULL REFERENCES supplier_profiles(organization_id),
  certification_type text NOT NULL,
  certificate_number text,
  issuing_authority text,
  valid_from date,
  valid_until date,
  file_asset_id uuid REFERENCES file_assets(id),
  status text NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'VERIFIED', 'EXPIRED', 'REVOKED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from)
);

CREATE TABLE facilities (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  supplier_organization_id uuid REFERENCES supplier_profiles(organization_id),
  location_id uuid NOT NULL REFERENCES locations(id),
  code text NOT NULL UNIQUE,
  name text NOT NULL,
  facility_type text NOT NULL
    CHECK (facility_type IN ('WAREHOUSE', 'BONDED_WAREHOUSE', 'CFS', 'FBA', 'CROSS_DOCK', 'RAIL_RAMP')),
  bonded boolean NOT NULL DEFAULT false,
  total_capacity_cbm numeric(18,4) CHECK (total_capacity_cbm IS NULL OR total_capacity_cbm >= 0),
  capabilities jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE', 'INACTIVE', 'FULL', 'MAINTENANCE')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE supplier_service_offerings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  supplier_organization_id uuid NOT NULL REFERENCES supplier_profiles(organization_id),
  service_definition_id uuid NOT NULL REFERENCES service_definitions(id),
  offering_code text NOT NULL,
  name text NOT NULL,
  fulfillment_mode text NOT NULL DEFAULT 'DIRECT'
    CHECK (fulfillment_mode IN ('DIRECT', 'BROKERED', 'PARTNER')),
  lead_time_hours integer CHECK (lead_time_hours IS NULL OR lead_time_hours >= 0),
  min_weight_kg numeric(18,4) CHECK (min_weight_kg IS NULL OR min_weight_kg >= 0),
  max_weight_kg numeric(18,4) CHECK (max_weight_kg IS NULL OR max_weight_kg >= 0),
  min_volume_cbm numeric(18,4) CHECK (min_volume_cbm IS NULL OR min_volume_cbm >= 0),
  max_volume_cbm numeric(18,4) CHECK (max_volume_cbm IS NULL OR max_volume_cbm >= 0),
  constraints jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('DRAFT', 'ACTIVE', 'PAUSED', 'INACTIVE')),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (supplier_organization_id, offering_code),
  CHECK (max_weight_kg IS NULL OR min_weight_kg IS NULL OR max_weight_kg >= min_weight_kg),
  CHECK (max_volume_cbm IS NULL OR min_volume_cbm IS NULL OR max_volume_cbm >= min_volume_cbm)
);

CREATE INDEX ix_offerings_service_active
  ON supplier_service_offerings (service_definition_id, supplier_organization_id)
  WHERE status = 'ACTIVE';

CREATE TABLE supplier_service_coverages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  offering_id uuid NOT NULL REFERENCES supplier_service_offerings(id) ON DELETE CASCADE,
  origin_country char(2),
  origin_province_state text,
  origin_city text,
  origin_fsa text,
  destination_country char(2),
  destination_province_state text,
  destination_city text,
  destination_fsa text,
  transport_mode text,
  effective_from date,
  effective_until date,
  additional_conditions jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE', 'INACTIVE')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (origin_country IS NULL OR origin_country ~ '^[A-Z]{2}$'),
  CHECK (destination_country IS NULL OR destination_country ~ '^[A-Z]{2}$'),
  CHECK (origin_fsa IS NULL OR origin_fsa ~ '^[A-Z][0-9][A-Z]$'),
  CHECK (destination_fsa IS NULL OR destination_fsa ~ '^[A-Z][0-9][A-Z]$'),
  CHECK (effective_until IS NULL OR effective_from IS NULL OR effective_until >= effective_from)
);

CREATE INDEX ix_coverage_destination
  ON supplier_service_coverages (destination_country, destination_province_state, destination_city, destination_fsa)
  WHERE status = 'ACTIVE';

-- ---------------------------------------------------------------------------
-- Shipment Request and Logistics Planning
-- ---------------------------------------------------------------------------

CREATE TABLE shipment_requests (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  request_number text NOT NULL UNIQUE,
  customer_organization_id uuid NOT NULL REFERENCES organizations(id),
  submitted_by_user_id uuid REFERENCES users(id),
  sales_owner_user_id uuid REFERENCES users(id),
  origin_location_id uuid NOT NULL REFERENCES locations(id),
  destination_location_id uuid NOT NULL REFERENCES locations(id),
  status text NOT NULL DEFAULT 'DRAFT'
    CHECK (status IN ('DRAFT', 'SUBMITTED', 'PLANNING', 'PLAN_READY', 'RFQ_OPEN', 'QUOTED', 'ORDERED', 'CANCELLED')),
  cargo_type text NOT NULL,
  cargo_description text,
  hs_code text,
  incoterm text,
  hazardous boolean NOT NULL DEFAULT false,
  temperature_controlled boolean NOT NULL DEFAULT false,
  ready_from timestamptz NOT NULL,
  ready_until timestamptz,
  total_pieces integer NOT NULL DEFAULT 1 CHECK (total_pieces > 0),
  total_pallets integer CHECK (total_pallets IS NULL OR total_pallets >= 0),
  total_weight_kg numeric(18,4) NOT NULL CHECK (total_weight_kg > 0),
  total_volume_cbm numeric(18,4) NOT NULL CHECK (total_volume_cbm > 0),
  declared_value numeric(18,4) CHECK (declared_value IS NULL OR declared_value >= 0),
  declared_value_currency char(3),
  customer_reference text,
  special_instructions text,
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  submitted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (ready_until IS NULL OR ready_until >= ready_from),
  CHECK (declared_value_currency IS NULL OR declared_value_currency ~ '^[A-Z]{3}$')
);

CREATE INDEX ix_shipment_requests_customer
  ON shipment_requests (customer_organization_id, created_at DESC);
CREATE INDEX ix_shipment_requests_sales_queue
  ON shipment_requests (sales_owner_user_id, status, ready_from);

CREATE TABLE shipment_cargo_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  shipment_request_id uuid NOT NULL REFERENCES shipment_requests(id) ON DELETE CASCADE,
  line_number integer NOT NULL CHECK (line_number > 0),
  description text NOT NULL,
  packaging_type text,
  pieces integer NOT NULL CHECK (pieces > 0),
  weight_kg numeric(18,4) NOT NULL CHECK (weight_kg > 0),
  volume_cbm numeric(18,4) NOT NULL CHECK (volume_cbm > 0),
  length_cm numeric(18,4) CHECK (length_cm IS NULL OR length_cm > 0),
  width_cm numeric(18,4) CHECK (width_cm IS NULL OR width_cm > 0),
  height_cm numeric(18,4) CHECK (height_cm IS NULL OR height_cm > 0),
  stackable boolean,
  hazardous_un_number text,
  attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (shipment_request_id, line_number)
);

CREATE TABLE shipment_request_services (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  shipment_request_id uuid NOT NULL REFERENCES shipment_requests(id) ON DELETE CASCADE,
  service_definition_id uuid NOT NULL REFERENCES service_definitions(id),
  requirement_level text NOT NULL DEFAULT 'REQUIRED'
    CHECK (requirement_level IN ('REQUIRED', 'PREFERRED', 'OPTIONAL')),
  service_options jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (shipment_request_id, service_definition_id)
);

CREATE TABLE logistics_plans (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  shipment_request_id uuid NOT NULL REFERENCES shipment_requests(id),
  revision integer NOT NULL CHECK (revision > 0),
  generation_mode text NOT NULL
    CHECK (generation_mode IN ('RULES', 'AI', 'HYBRID', 'MANUAL')),
  ai_run_id uuid REFERENCES ai_runs(id),
  status text NOT NULL DEFAULT 'DRAFT'
    CHECK (status IN ('DRAFT', 'VALIDATING', 'REVIEW_REQUIRED', 'APPROVED', 'REJECTED', 'SUPERSEDED')),
  title text NOT NULL,
  summary text,
  validation_result jsonb NOT NULL DEFAULT '{}'::jsonb,
  constraints_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  approved_by_user_id uuid REFERENCES users(id),
  approved_at timestamptz,
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (shipment_request_id, revision),
  UNIQUE (id, shipment_request_id)
);

CREATE INDEX ix_logistics_plans_request_status
  ON logistics_plans (shipment_request_id, status, revision DESC);

CREATE TABLE plan_legs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  logistics_plan_id uuid NOT NULL REFERENCES logistics_plans(id) ON DELETE CASCADE,
  sequence_number integer NOT NULL CHECK (sequence_number > 0),
  service_definition_id uuid NOT NULL REFERENCES service_definitions(id),
  leg_type text NOT NULL
    CHECK (leg_type IN ('TRANSPORT', 'HANDLING', 'CUSTOMS', 'STORAGE', 'VALUE_ADDED', 'TAX_IMPORT')),
  transport_mode text,
  from_location_id uuid REFERENCES locations(id),
  to_location_id uuid REFERENCES locations(id),
  planned_start_at timestamptz,
  planned_end_at timestamptz,
  estimated_duration_hours integer CHECK (estimated_duration_hours IS NULL OR estimated_duration_hours >= 0),
  supplier_requirements jsonb NOT NULL DEFAULT '{}'::jsonb,
  instructions text,
  status text NOT NULL DEFAULT 'PLANNED'
    CHECK (status IN ('PLANNED', 'READY_FOR_RFQ', 'RFQ_OPEN', 'SOURCED', 'CANCELLED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (logistics_plan_id, sequence_number),
  CHECK (planned_end_at IS NULL OR planned_start_at IS NULL OR planned_end_at >= planned_start_at)
);

CREATE TABLE plan_leg_dependencies (
  plan_leg_id uuid NOT NULL REFERENCES plan_legs(id) ON DELETE CASCADE,
  depends_on_plan_leg_id uuid NOT NULL REFERENCES plan_legs(id) ON DELETE CASCADE,
  dependency_type text NOT NULL DEFAULT 'FINISH_TO_START'
    CHECK (dependency_type IN ('FINISH_TO_START', 'START_TO_START')),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (plan_leg_id, depends_on_plan_leg_id),
  CHECK (plan_leg_id <> depends_on_plan_leg_id)
);

-- ---------------------------------------------------------------------------
-- RFQ, supplier selection, dispatch, and normalized supplier quotes
-- ---------------------------------------------------------------------------

CREATE TABLE rfqs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  rfq_number text NOT NULL UNIQUE,
  shipment_request_id uuid NOT NULL REFERENCES shipment_requests(id),
  logistics_plan_id uuid NOT NULL REFERENCES logistics_plans(id),
  round_number integer NOT NULL DEFAULT 1 CHECK (round_number > 0),
  status text NOT NULL DEFAULT 'DRAFT'
    CHECK (status IN ('DRAFT', 'PUBLISHED', 'PARTIALLY_RESPONDED', 'CLOSED', 'COMPLETED', 'CANCELLED')),
  response_due_at timestamptz NOT NULL,
  instructions text,
  created_by_user_id uuid NOT NULL REFERENCES users(id),
  published_at timestamptz,
  closed_at timestamptz,
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (shipment_request_id, logistics_plan_id, round_number),
  FOREIGN KEY (logistics_plan_id, shipment_request_id)
    REFERENCES logistics_plans(id, shipment_request_id),
  CHECK (response_due_at > created_at)
);

CREATE INDEX ix_rfqs_open_due
  ON rfqs (response_due_at) WHERE status IN ('PUBLISHED', 'PARTIALLY_RESPONDED');

CREATE TABLE rfq_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  rfq_id uuid NOT NULL REFERENCES rfqs(id) ON DELETE CASCADE,
  plan_leg_id uuid NOT NULL REFERENCES plan_legs(id),
  service_definition_id uuid NOT NULL REFERENCES service_definitions(id),
  line_number integer NOT NULL CHECK (line_number > 0),
  required_from timestamptz,
  required_until timestamptz,
  quantity numeric(18,4),
  unit text,
  scope_snapshot jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (rfq_id, line_number),
  UNIQUE (rfq_id, plan_leg_id),
  CHECK (required_until IS NULL OR required_from IS NULL OR required_until >= required_from),
  CHECK (quantity IS NULL OR quantity > 0)
);

CREATE TABLE rfq_invitations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  rfq_id uuid NOT NULL REFERENCES rfqs(id) ON DELETE CASCADE,
  supplier_organization_id uuid NOT NULL REFERENCES supplier_profiles(organization_id),
  primary_channel text NOT NULL
    CHECK (primary_channel IN ('EMAIL', 'API', 'EXCEL', 'WEBHOOK', 'PORTAL')),
  selection_score numeric(7,4),
  selection_reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
  status text NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'QUEUED', 'SENT', 'DELIVERED', 'OPENED', 'RESPONDED', 'DECLINED', 'FAILED', 'CANCELLED')),
  sent_at timestamptz,
  delivered_at timestamptz,
  responded_at timestamptz,
  decline_reason text,
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (rfq_id, supplier_organization_id),
  UNIQUE (id, supplier_organization_id),
  CHECK (selection_score IS NULL OR selection_score BETWEEN 0 AND 100)
);

CREATE INDEX ix_rfq_invitations_supplier_queue
  ON rfq_invitations (supplier_organization_id, status, created_at DESC);

CREATE TABLE rfq_dispatch_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  invitation_id uuid NOT NULL REFERENCES rfq_invitations(id) ON DELETE CASCADE,
  connection_id uuid REFERENCES integration_connections(id),
  channel text NOT NULL
    CHECK (channel IN ('EMAIL', 'API', 'EXCEL', 'WEBHOOK', 'PORTAL')),
  attempt_number integer NOT NULL CHECK (attempt_number > 0),
  idempotency_key text NOT NULL UNIQUE,
  status text NOT NULL DEFAULT 'QUEUED'
    CHECK (status IN ('QUEUED', 'SENDING', 'SENT', 'DELIVERED', 'RETRY_WAIT', 'FAILED')),
  external_message_id text,
  request_asset_id uuid REFERENCES file_assets(id),
  response_asset_id uuid REFERENCES file_assets(id),
  error_code text,
  error_message text,
  next_attempt_at timestamptz,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (invitation_id, channel, attempt_number)
);

CREATE INDEX ix_rfq_dispatch_retry
  ON rfq_dispatch_attempts (next_attempt_at)
  WHERE status IN ('QUEUED', 'RETRY_WAIT');

CREATE TABLE supplier_quotes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  invitation_id uuid NOT NULL REFERENCES rfq_invitations(id),
  supplier_organization_id uuid NOT NULL REFERENCES supplier_profiles(organization_id),
  revision integer NOT NULL CHECK (revision > 0),
  previous_revision_id uuid REFERENCES supplier_quotes(id),
  supplier_quote_reference text,
  source_channel text NOT NULL
    CHECK (source_channel IN ('EMAIL', 'API', 'EXCEL', 'WEBHOOK', 'PORTAL', 'MANUAL')),
  source_asset_id uuid REFERENCES file_assets(id),
  status text NOT NULL DEFAULT 'DRAFT'
    CHECK (status IN ('DRAFT', 'PARSED', 'REVIEW_REQUIRED', 'VALIDATED', 'SUBMITTED', 'WITHDRAWN', 'EXPIRED', 'REJECTED')),
  currency char(3) NOT NULL,
  total_amount numeric(18,4) NOT NULL CHECK (total_amount >= 0),
  transit_time_hours integer CHECK (transit_time_hours IS NULL OR transit_time_hours >= 0),
  free_time_hours integer CHECK (free_time_hours IS NULL OR free_time_hours >= 0),
  valid_from timestamptz,
  valid_until timestamptz,
  notes text,
  submitted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (invitation_id, revision),
  FOREIGN KEY (invitation_id, supplier_organization_id)
    REFERENCES rfq_invitations(id, supplier_organization_id),
  CHECK (currency ~ '^[A-Z]{3}$'),
  CHECK (valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from),
  CHECK (previous_revision_id IS NULL OR previous_revision_id <> id)
);

CREATE INDEX ix_supplier_quotes_invitation_status
  ON supplier_quotes (invitation_id, status, revision DESC);

CREATE TABLE supplier_quote_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  supplier_quote_id uuid NOT NULL REFERENCES supplier_quotes(id) ON DELETE CASCADE,
  rfq_item_id uuid NOT NULL REFERENCES rfq_items(id),
  service_definition_id uuid NOT NULL REFERENCES service_definitions(id),
  line_number integer NOT NULL CHECK (line_number > 0),
  amount numeric(18,4) NOT NULL CHECK (amount >= 0),
  transit_time_hours integer CHECK (transit_time_hours IS NULL OR transit_time_hours >= 0),
  free_time_hours integer CHECK (free_time_hours IS NULL OR free_time_hours >= 0),
  available_from timestamptz,
  available_until timestamptz,
  notes text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (supplier_quote_id, line_number),
  UNIQUE (supplier_quote_id, rfq_item_id),
  CHECK (available_until IS NULL OR available_from IS NULL OR available_until >= available_from)
);

CREATE TABLE supplier_quote_charges (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  supplier_quote_item_id uuid NOT NULL REFERENCES supplier_quote_items(id) ON DELETE CASCADE,
  charge_code text NOT NULL,
  charge_name text NOT NULL,
  charge_type text NOT NULL
    CHECK (charge_type IN ('BASE', 'THC', 'DOC', 'FUEL', 'CUSTOMS', 'TAX', 'ACCESSORIAL', 'DISCOUNT', 'OTHER')),
  calculation_basis text NOT NULL DEFAULT 'FLAT'
    CHECK (calculation_basis IN ('FLAT', 'PER_KG', 'PER_CBM', 'PER_PALLET', 'PERCENT', 'PER_SHIPMENT', 'INCLUDED')),
  quantity numeric(18,4),
  unit_rate numeric(18,4),
  amount numeric(18,4) NOT NULL,
  currency char(3) NOT NULL,
  included boolean NOT NULL DEFAULT false,
  taxable boolean NOT NULL DEFAULT false,
  source_text text,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (currency ~ '^[A-Z]{3}$'),
  CHECK (quantity IS NULL OR quantity >= 0)
);

CREATE INDEX ix_supplier_quote_charges_item ON supplier_quote_charges (supplier_quote_item_id, charge_type);

CREATE TABLE quote_parse_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  invitation_id uuid NOT NULL REFERENCES rfq_invitations(id),
  source_asset_id uuid NOT NULL REFERENCES file_assets(id),
  ai_run_id uuid REFERENCES ai_runs(id),
  supplier_quote_id uuid REFERENCES supplier_quotes(id),
  parser_type text NOT NULL
    CHECK (parser_type IN ('AI', 'RULES', 'HYBRID', 'MANUAL')),
  status text NOT NULL DEFAULT 'QUEUED'
    CHECK (status IN ('QUEUED', 'PARSING', 'VALIDATED', 'REVIEW_REQUIRED', 'FAILED')),
  confidence numeric(7,4),
  extracted_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  validation_errors jsonb NOT NULL DEFAULT '[]'::jsonb,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 100)
);

CREATE INDEX ix_quote_parse_runs_queue
  ON quote_parse_runs (status, created_at) WHERE status IN ('QUEUED', 'PARSING', 'REVIEW_REQUIRED');

-- ---------------------------------------------------------------------------
-- Customer Quote Center
-- ---------------------------------------------------------------------------

CREATE TABLE customer_quotes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  quote_number text NOT NULL,
  shipment_request_id uuid NOT NULL REFERENCES shipment_requests(id),
  logistics_plan_id uuid NOT NULL REFERENCES logistics_plans(id),
  revision integer NOT NULL CHECK (revision > 0),
  previous_revision_id uuid REFERENCES customer_quotes(id),
  status text NOT NULL DEFAULT 'DRAFT'
    CHECK (status IN ('DRAFT', 'READY_FOR_REVIEW', 'PUBLISHED', 'ACCEPTED', 'DECLINED', 'EXPIRED', 'SUPERSEDED', 'CANCELLED')),
  currency char(3) NOT NULL DEFAULT 'CAD',
  valid_until timestamptz NOT NULL,
  created_by_user_id uuid NOT NULL REFERENCES users(id),
  published_at timestamptz,
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (shipment_request_id, revision),
  UNIQUE (quote_number, revision),
  FOREIGN KEY (logistics_plan_id, shipment_request_id)
    REFERENCES logistics_plans(id, shipment_request_id),
  CHECK (currency ~ '^[A-Z]{3}$'),
  CHECK (valid_until > created_at),
  CHECK (previous_revision_id IS NULL OR previous_revision_id <> id)
);

CREATE INDEX ix_customer_quotes_request
  ON customer_quotes (shipment_request_id, revision DESC);

CREATE TABLE quote_options (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_quote_id uuid NOT NULL REFERENCES customer_quotes(id) ON DELETE CASCADE,
  option_code text NOT NULL,
  option_type text NOT NULL
    CHECK (option_type IN ('LOWEST_PRICE', 'FASTEST', 'RECOMMENDED', 'DDP', 'SELF_IMPORT', 'CUSTOM')),
  title text NOT NULL,
  description text,
  incoterm text,
  total_cost_amount numeric(18,4) NOT NULL CHECK (total_cost_amount >= 0),
  total_sell_amount numeric(18,4) NOT NULL CHECK (total_sell_amount >= 0),
  margin_amount numeric(18,4) NOT NULL,
  margin_percent numeric(9,4),
  estimated_transit_hours integer CHECK (estimated_transit_hours IS NULL OR estimated_transit_hours >= 0),
  recommendation_score numeric(7,4),
  recommendation_reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
  is_recommended boolean NOT NULL DEFAULT false,
  risk_flags jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (customer_quote_id, option_code),
  UNIQUE (id, customer_quote_id),
  CHECK (recommendation_score IS NULL OR recommendation_score BETWEEN 0 AND 100)
);

CREATE UNIQUE INDEX uq_quote_options_recommended
  ON quote_options (customer_quote_id) WHERE is_recommended = true;

CREATE TABLE quote_option_legs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  quote_option_id uuid NOT NULL REFERENCES quote_options(id) ON DELETE CASCADE,
  sequence_number integer NOT NULL CHECK (sequence_number > 0),
  plan_leg_id uuid NOT NULL REFERENCES plan_legs(id),
  supplier_quote_item_id uuid NOT NULL REFERENCES supplier_quote_items(id),
  supplier_organization_id uuid NOT NULL REFERENCES supplier_profiles(organization_id),
  buy_amount numeric(18,4) NOT NULL CHECK (buy_amount >= 0),
  sell_amount numeric(18,4) NOT NULL CHECK (sell_amount >= 0),
  currency char(3) NOT NULL,
  transit_time_hours integer CHECK (transit_time_hours IS NULL OR transit_time_hours >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (quote_option_id, sequence_number),
  UNIQUE (quote_option_id, plan_leg_id),
  CHECK (currency ~ '^[A-Z]{3}$')
);

CREATE TABLE quote_option_charges (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  quote_option_id uuid NOT NULL REFERENCES quote_options(id) ON DELETE CASCADE,
  quote_option_leg_id uuid REFERENCES quote_option_legs(id) ON DELETE CASCADE,
  charge_code text NOT NULL,
  label text NOT NULL,
  amount numeric(18,4) NOT NULL,
  currency char(3) NOT NULL,
  visibility text NOT NULL DEFAULT 'CUSTOMER'
    CHECK (visibility IN ('CUSTOMER', 'INTERNAL', 'BOTH')),
  sort_order integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (currency ~ '^[A-Z]{3}$')
);

CREATE TABLE customer_quote_acceptances (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_quote_id uuid NOT NULL UNIQUE REFERENCES customer_quotes(id),
  quote_option_id uuid NOT NULL REFERENCES quote_options(id),
  accepted_by_user_id uuid REFERENCES users(id),
  accepted_by_name text,
  accepted_by_email text,
  terms_version text NOT NULL,
  acceptance_ip inet,
  acceptance_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  accepted_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id, quote_option_id),
  FOREIGN KEY (quote_option_id, customer_quote_id)
    REFERENCES quote_options(id, customer_quote_id)
);

-- ---------------------------------------------------------------------------
-- Orders, consolidation matching, and price locks
-- ---------------------------------------------------------------------------

CREATE TABLE orders (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  order_number text NOT NULL UNIQUE,
  customer_organization_id uuid NOT NULL REFERENCES organizations(id),
  shipment_request_id uuid NOT NULL REFERENCES shipment_requests(id),
  quote_acceptance_id uuid NOT NULL UNIQUE REFERENCES customer_quote_acceptances(id),
  accepted_quote_option_id uuid NOT NULL REFERENCES quote_options(id),
  status text NOT NULL DEFAULT 'CONFIRMED'
    CHECK (status IN ('CONFIRMED', 'WAITING_CONSOLIDATION', 'ALLOCATED', 'IN_FULFILLMENT', 'COMPLETED', 'CANCELLED')),
  currency char(3) NOT NULL,
  total_sell_amount numeric(18,4) NOT NULL CHECK (total_sell_amount >= 0),
  customer_reference text,
  confirmed_at timestamptz NOT NULL DEFAULT now(),
  cancelled_at timestamptz,
  cancel_reason text,
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (quote_acceptance_id, accepted_quote_option_id)
    REFERENCES customer_quote_acceptances(id, quote_option_id),
  CHECK (currency ~ '^[A-Z]{3}$')
);

CREATE INDEX ix_orders_customer_created ON orders (customer_organization_id, created_at DESC);
CREATE INDEX ix_orders_status ON orders (status, confirmed_at);

CREATE TABLE consolidation_pools (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  pool_number text NOT NULL UNIQUE,
  destination_country char(2) NOT NULL DEFAULT 'CA',
  destination_province_state text,
  destination_city text NOT NULL,
  destination_fsa text,
  destination_facility_id uuid REFERENCES facilities(id),
  primary_service_definition_id uuid REFERENCES service_definitions(id),
  planned_open_at timestamptz NOT NULL,
  planned_close_at timestamptz NOT NULL,
  planned_departure_at timestamptz,
  min_volume_cbm numeric(18,4) NOT NULL DEFAULT 0 CHECK (min_volume_cbm >= 0),
  target_volume_cbm numeric(18,4) NOT NULL CHECK (target_volume_cbm > 0),
  max_volume_cbm numeric(18,4) NOT NULL CHECK (max_volume_cbm > 0),
  min_weight_kg numeric(18,4) NOT NULL DEFAULT 0 CHECK (min_weight_kg >= 0),
  target_weight_kg numeric(18,4) NOT NULL CHECK (target_weight_kg > 0),
  max_weight_kg numeric(18,4) NOT NULL CHECK (max_weight_kg > 0),
  status text NOT NULL DEFAULT 'PLANNED'
    CHECK (status IN ('PLANNED', 'OPEN', 'LOCKING', 'CONFIRMED', 'DISPATCHED', 'CLOSED', 'CANCELLED')),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (destination_country ~ '^[A-Z]{2}$'),
  CHECK (destination_fsa IS NULL OR destination_fsa ~ '^[A-Z][0-9][A-Z]$'),
  CHECK (planned_close_at > planned_open_at),
  CHECK (planned_departure_at IS NULL OR planned_departure_at >= planned_close_at),
  CHECK (max_volume_cbm >= target_volume_cbm AND target_volume_cbm >= min_volume_cbm),
  CHECK (max_weight_kg >= target_weight_kg AND target_weight_kg >= min_weight_kg)
);

CREATE INDEX ix_consolidation_pools_match
  ON consolidation_pools (destination_country, destination_province_state, destination_city, planned_close_at)
  WHERE status IN ('PLANNED', 'OPEN', 'LOCKING');

CREATE TABLE consolidation_pool_memberships (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  consolidation_pool_id uuid NOT NULL REFERENCES consolidation_pools(id),
  order_id uuid NOT NULL REFERENCES orders(id),
  status text NOT NULL DEFAULT 'CANDIDATE'
    CHECK (status IN ('CANDIDATE', 'OFFERED', 'RESERVED', 'CONFIRMED', 'RELEASED', 'REJECTED')),
  match_score numeric(7,4),
  match_reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
  committed_volume_cbm numeric(18,4) NOT NULL CHECK (committed_volume_cbm > 0),
  committed_weight_kg numeric(18,4) NOT NULL CHECK (committed_weight_kg > 0),
  reserved_at timestamptz,
  confirmed_at timestamptz,
  released_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (consolidation_pool_id, order_id),
  CHECK (match_score IS NULL OR match_score BETWEEN 0 AND 100)
);

CREATE INDEX ix_pool_memberships_order ON consolidation_pool_memberships (order_id, status);

CREATE TABLE price_locks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lock_type text NOT NULL CHECK (lock_type IN ('BUY', 'SELL')),
  supplier_quote_id uuid REFERENCES supplier_quotes(id),
  quote_option_id uuid REFERENCES quote_options(id),
  order_id uuid REFERENCES orders(id),
  locked_amount numeric(18,4) NOT NULL CHECK (locked_amount >= 0),
  currency char(3) NOT NULL,
  status text NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE', 'CONSUMED', 'EXPIRED', 'RELEASED', 'VOID')),
  locked_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz,
  released_at timestamptz,
  created_by_user_id uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (currency ~ '^[A-Z]{3}$'),
  CHECK (num_nonnulls(supplier_quote_id, quote_option_id) = 1),
  CHECK (expires_at > locked_at)
);

CREATE INDEX ix_price_locks_active
  ON price_locks (expires_at) WHERE status = 'ACTIVE';

CREATE TABLE shipments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  shipment_number text NOT NULL UNIQUE,
  logistics_plan_id uuid NOT NULL REFERENCES logistics_plans(id),
  consolidation_pool_id uuid REFERENCES consolidation_pools(id),
  master_reference text,
  status text NOT NULL DEFAULT 'PLANNED'
    CHECK (status IN ('PLANNED', 'BOOKED', 'IN_TRANSIT', 'AT_WAREHOUSE', 'OUT_FOR_DELIVERY', 'DELIVERED', 'EXCEPTION', 'CANCELLED')),
  planned_departure_at timestamptz,
  planned_arrival_at timestamptz,
  actual_departure_at timestamptz,
  actual_arrival_at timestamptz,
  total_weight_kg numeric(18,4) NOT NULL CHECK (total_weight_kg > 0),
  total_volume_cbm numeric(18,4) NOT NULL CHECK (total_volume_cbm > 0),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (planned_arrival_at IS NULL OR planned_departure_at IS NULL OR planned_arrival_at >= planned_departure_at),
  CHECK (actual_arrival_at IS NULL OR actual_departure_at IS NULL OR actual_arrival_at >= actual_departure_at)
);

CREATE INDEX ix_shipments_status ON shipments (status, planned_departure_at);

CREATE TABLE shipment_orders (
  shipment_id uuid NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
  order_id uuid NOT NULL REFERENCES orders(id),
  allocated_weight_kg numeric(18,4) NOT NULL CHECK (allocated_weight_kg > 0),
  allocated_volume_cbm numeric(18,4) NOT NULL CHECK (allocated_volume_cbm > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (shipment_id, order_id)
);

-- ---------------------------------------------------------------------------
-- Fulfillment and unified Tracking Timeline
-- ---------------------------------------------------------------------------

CREATE TABLE fulfillment_tasks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  task_number text NOT NULL UNIQUE,
  shipment_id uuid NOT NULL REFERENCES shipments(id),
  plan_leg_id uuid NOT NULL REFERENCES plan_legs(id),
  service_definition_id uuid NOT NULL REFERENCES service_definitions(id),
  supplier_organization_id uuid NOT NULL REFERENCES supplier_profiles(organization_id),
  status text NOT NULL DEFAULT 'PENDING_ASSIGNMENT'
    CHECK (status IN ('PENDING_ASSIGNMENT', 'ASSIGNED', 'ACCEPTED', 'IN_PROGRESS', 'COMPLETED', 'EXCEPTION', 'REJECTED', 'CANCELLED')),
  scheduled_start_at timestamptz,
  scheduled_end_at timestamptz,
  actual_start_at timestamptz,
  actual_end_at timestamptz,
  buy_amount numeric(18,4) NOT NULL CHECK (buy_amount >= 0),
  sell_amount numeric(18,4) NOT NULL CHECK (sell_amount >= 0),
  currency char(3) NOT NULL,
  instructions text,
  exception_code text,
  exception_note text,
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  assigned_at timestamptz,
  accepted_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (shipment_id, plan_leg_id),
  CHECK (currency ~ '^[A-Z]{3}$'),
  CHECK (scheduled_end_at IS NULL OR scheduled_start_at IS NULL OR scheduled_end_at >= scheduled_start_at),
  CHECK (actual_end_at IS NULL OR actual_start_at IS NULL OR actual_end_at >= actual_start_at)
);

CREATE INDEX ix_fulfillment_tasks_supplier_queue
  ON fulfillment_tasks (supplier_organization_id, status, scheduled_start_at);
CREATE INDEX ix_fulfillment_tasks_shipment ON fulfillment_tasks (shipment_id, status);

CREATE TABLE fulfillment_task_dependencies (
  fulfillment_task_id uuid NOT NULL REFERENCES fulfillment_tasks(id) ON DELETE CASCADE,
  depends_on_task_id uuid NOT NULL REFERENCES fulfillment_tasks(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (fulfillment_task_id, depends_on_task_id),
  CHECK (fulfillment_task_id <> depends_on_task_id)
);

CREATE TABLE fulfillment_task_status_history (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  fulfillment_task_id uuid NOT NULL REFERENCES fulfillment_tasks(id),
  from_status text,
  to_status text NOT NULL,
  reason_code text,
  note text,
  actor_user_id uuid REFERENCES users(id),
  actor_organization_id uuid REFERENCES organizations(id),
  occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_task_status_history_task
  ON fulfillment_task_status_history (fulfillment_task_id, occurred_at);

CREATE TABLE tracking_milestones (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  shipment_id uuid NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
  fulfillment_task_id uuid REFERENCES fulfillment_tasks(id),
  milestone_code text NOT NULL,
  label text NOT NULL,
  sequence_number integer NOT NULL CHECK (sequence_number > 0),
  status text NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'EXPECTED', 'COMPLETED', 'MISSED', 'EXCEPTION', 'SKIPPED')),
  planned_at timestamptz,
  estimated_at timestamptz,
  actual_at timestamptz,
  location_id uuid REFERENCES locations(id),
  source text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (shipment_id, milestone_code)
);

CREATE TABLE tracking_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  shipment_id uuid NOT NULL REFERENCES shipments(id),
  fulfillment_task_id uuid REFERENCES fulfillment_tasks(id),
  milestone_id uuid REFERENCES tracking_milestones(id),
  source_type text NOT NULL
    CHECK (source_type IN ('SUPPLIER', 'CARRIER_API', 'WEBHOOK', 'PLATFORM', 'CUSTOMER', 'SYSTEM')),
  source_organization_id uuid REFERENCES organizations(id),
  external_event_id text,
  event_code text NOT NULL,
  event_label text NOT NULL,
  event_status text,
  occurred_at timestamptz NOT NULL,
  received_at timestamptz NOT NULL DEFAULT now(),
  location_id uuid REFERENCES locations(id),
  message text,
  raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  payload_hash char(64) NOT NULL,
  created_by_user_id uuid REFERENCES users(id),
  CHECK (payload_hash ~ '^[0-9a-f]{64}$')
);

CREATE UNIQUE INDEX uq_tracking_events_external
  ON tracking_events (source_type, source_organization_id, external_event_id)
  WHERE external_event_id IS NOT NULL;
CREATE INDEX ix_tracking_events_timeline
  ON tracking_events (shipment_id, occurred_at, id);

CREATE TABLE supplier_complaints (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  complaint_number text NOT NULL UNIQUE,
  supplier_organization_id uuid NOT NULL REFERENCES supplier_profiles(organization_id),
  customer_organization_id uuid REFERENCES organizations(id),
  order_id uuid REFERENCES orders(id),
  shipment_id uuid REFERENCES shipments(id),
  fulfillment_task_id uuid REFERENCES fulfillment_tasks(id),
  category text NOT NULL,
  severity text NOT NULL
    CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
  status text NOT NULL DEFAULT 'OPEN'
    CHECK (status IN ('OPEN', 'INVESTIGATING', 'WAITING_SUPPLIER', 'RESOLVED', 'REJECTED', 'CANCELLED')),
  summary text NOT NULL,
  details text,
  reported_by_user_id uuid REFERENCES users(id),
  assigned_to_user_id uuid REFERENCES users(id),
  resolution_code text,
  resolution_note text,
  resolved_at timestamptz,
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (num_nonnulls(order_id, shipment_id, fulfillment_task_id) >= 1)
);

CREATE INDEX ix_supplier_complaints_queue
  ON supplier_complaints (supplier_organization_id, status, severity, created_at DESC);

-- ---------------------------------------------------------------------------
-- Supplier performance snapshots
-- ---------------------------------------------------------------------------

CREATE TABLE supplier_kpi_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  supplier_organization_id uuid NOT NULL REFERENCES supplier_profiles(organization_id),
  window_start date NOT NULL,
  window_end date NOT NULL,
  calculated_at timestamptz NOT NULL DEFAULT now(),
  response_rate numeric(7,4) CHECK (response_rate IS NULL OR response_rate BETWEEN 0 AND 100),
  win_rate numeric(7,4) CHECK (win_rate IS NULL OR win_rate BETWEEN 0 AND 100),
  fulfillment_rate numeric(7,4) CHECK (fulfillment_rate IS NULL OR fulfillment_rate BETWEEN 0 AND 100),
  complaint_rate numeric(7,4) CHECK (complaint_rate IS NULL OR complaint_rate BETWEEN 0 AND 100),
  average_profit_amount numeric(18,4),
  profit_currency char(3),
  average_quote_response_minutes numeric(18,4) CHECK (average_quote_response_minutes IS NULL OR average_quote_response_minutes >= 0),
  rfq_count integer NOT NULL DEFAULT 0 CHECK (rfq_count >= 0),
  quote_count integer NOT NULL DEFAULT 0 CHECK (quote_count >= 0),
  order_count integer NOT NULL DEFAULT 0 CHECK (order_count >= 0),
  complaint_count integer NOT NULL DEFAULT 0 CHECK (complaint_count >= 0),
  metric_version text NOT NULL,
  details jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (supplier_organization_id, window_start, window_end, metric_version),
  CHECK (window_end >= window_start),
  CHECK (profit_currency IS NULL OR profit_currency ~ '^[A-Z]{3}$')
);

CREATE INDEX ix_supplier_kpis_latest
  ON supplier_kpi_snapshots (supplier_organization_id, calculated_at DESC);

-- ---------------------------------------------------------------------------
-- Price Intelligence: Collector, Forecast, Recommendation, Dynamic Pricing
-- ---------------------------------------------------------------------------

CREATE TABLE price_observations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_type text NOT NULL
    CHECK (source_type IN ('SUPPLIER_QUOTE', 'TRANSACTION', 'RATE_CARD', 'HISTORICAL', 'MARKET')),
  source_entity_type text NOT NULL,
  source_entity_id uuid,
  source_reference text,
  supplier_organization_id uuid REFERENCES supplier_profiles(organization_id),
  customer_organization_id uuid REFERENCES organizations(id),
  service_definition_id uuid NOT NULL REFERENCES service_definitions(id),
  transport_mode text,
  origin_country char(2),
  origin_province_state text,
  origin_city text,
  origin_fsa text,
  destination_country char(2),
  destination_province_state text,
  destination_city text,
  destination_fsa text,
  cargo_type text,
  weight_kg numeric(18,4) CHECK (weight_kg IS NULL OR weight_kg > 0),
  volume_cbm numeric(18,4) CHECK (volume_cbm IS NULL OR volume_cbm > 0),
  unit_basis text NOT NULL
    CHECK (unit_basis IN ('SHIPMENT', 'KG', 'CBM', 'PALLET', 'CONTAINER', 'LEG')),
  original_amount numeric(18,4) NOT NULL CHECK (original_amount >= 0),
  original_currency char(3) NOT NULL,
  normalized_amount_cad numeric(18,4) NOT NULL CHECK (normalized_amount_cad >= 0),
  fx_rate_to_cad numeric(18,8) NOT NULL CHECK (fx_rate_to_cad > 0),
  charge_breakdown jsonb NOT NULL DEFAULT '{}'::jsonb,
  occurred_at timestamptz NOT NULL,
  effective_from timestamptz,
  effective_until timestamptz,
  visibility text NOT NULL DEFAULT 'PRIVATE'
    CHECK (visibility IN ('PRIVATE', 'PLATFORM', 'AGGREGATED')),
  quality_score numeric(7,4) NOT NULL DEFAULT 100 CHECK (quality_score BETWEEN 0 AND 100),
  lineage jsonb NOT NULL DEFAULT '{}'::jsonb,
  supersedes_observation_id uuid REFERENCES price_observations(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (origin_country IS NULL OR origin_country ~ '^[A-Z]{2}$'),
  CHECK (destination_country IS NULL OR destination_country ~ '^[A-Z]{2}$'),
  CHECK (origin_fsa IS NULL OR origin_fsa ~ '^[A-Z][0-9][A-Z]$'),
  CHECK (destination_fsa IS NULL OR destination_fsa ~ '^[A-Z][0-9][A-Z]$'),
  CHECK (original_currency ~ '^[A-Z]{3}$'),
  CHECK (effective_until IS NULL OR effective_from IS NULL OR effective_until >= effective_from),
  CHECK (supersedes_observation_id IS NULL OR supersedes_observation_id <> id)
);

CREATE INDEX ix_price_observations_segment
  ON price_observations (
    service_definition_id,
    destination_country,
    destination_province_state,
    destination_city,
    occurred_at DESC
  );
CREATE INDEX ix_price_observations_source
  ON price_observations (source_entity_type, source_entity_id);

CREATE TABLE price_forecast_models (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  version text NOT NULL,
  algorithm text NOT NULL,
  artifact_uri text NOT NULL,
  training_window_start timestamptz NOT NULL,
  training_window_end timestamptz NOT NULL,
  training_data_hash char(64) NOT NULL,
  metrics jsonb NOT NULL,
  status text NOT NULL DEFAULT 'CANDIDATE'
    CHECK (status IN ('CANDIDATE', 'SHADOW', 'ACTIVE', 'RETIRED', 'REJECTED')),
  approved_by_user_id uuid REFERENCES users(id),
  approved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (name, version),
  CHECK (training_window_end >= training_window_start),
  CHECK (training_data_hash ~ '^[0-9a-f]{64}$')
);

CREATE UNIQUE INDEX uq_price_forecast_model_active
  ON price_forecast_models (name) WHERE status = 'ACTIVE';

CREATE TABLE price_forecasts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  model_id uuid NOT NULL REFERENCES price_forecast_models(id),
  ai_run_id uuid REFERENCES ai_runs(id),
  segment_key text NOT NULL,
  service_definition_id uuid NOT NULL REFERENCES service_definitions(id),
  transport_mode text,
  origin_country char(2),
  origin_province_state text,
  origin_city text,
  destination_country char(2) NOT NULL DEFAULT 'CA',
  destination_province_state text,
  destination_city text NOT NULL,
  horizon_days integer NOT NULL CHECK (horizon_days IN (7, 14, 30)),
  target_date date NOT NULL,
  currency char(3) NOT NULL DEFAULT 'CAD',
  p10_amount numeric(18,4) NOT NULL CHECK (p10_amount >= 0),
  p50_amount numeric(18,4) NOT NULL CHECK (p50_amount >= 0),
  p90_amount numeric(18,4) NOT NULL CHECK (p90_amount >= 0),
  confidence numeric(7,4) NOT NULL CHECK (confidence BETWEEN 0 AND 100),
  observation_count integer NOT NULL CHECK (observation_count >= 0),
  training_cutoff_at timestamptz NOT NULL,
  generated_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  UNIQUE (model_id, segment_key, horizon_days, target_date),
  CHECK (currency ~ '^[A-Z]{3}$'),
  CHECK (p10_amount <= p50_amount AND p50_amount <= p90_amount),
  CHECK (expires_at > generated_at)
);

CREATE INDEX ix_price_forecasts_lookup
  ON price_forecasts (service_definition_id, destination_city, horizon_days, target_date, generated_at DESC);

CREATE TABLE price_recommendations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  recommendation_type text NOT NULL
    CHECK (recommendation_type IN ('SALES_PRICE', 'PROCUREMENT_TARGET')),
  shipment_request_id uuid REFERENCES shipment_requests(id),
  customer_quote_id uuid REFERENCES customer_quotes(id),
  quote_option_id uuid REFERENCES quote_options(id),
  forecast_id uuid REFERENCES price_forecasts(id),
  ai_run_id uuid REFERENCES ai_runs(id),
  currency char(3) NOT NULL,
  cost_basis_amount numeric(18,4) NOT NULL CHECK (cost_basis_amount >= 0),
  recommended_amount numeric(18,4) NOT NULL CHECK (recommended_amount >= 0),
  floor_amount numeric(18,4) NOT NULL CHECK (floor_amount >= 0),
  ceiling_amount numeric(18,4) NOT NULL CHECK (ceiling_amount >= 0),
  target_margin_percent numeric(9,4),
  confidence numeric(7,4) NOT NULL CHECK (confidence BETWEEN 0 AND 100),
  reason_codes jsonb NOT NULL DEFAULT '[]'::jsonb,
  evidence_snapshot jsonb NOT NULL,
  status text NOT NULL DEFAULT 'PROPOSED'
    CHECK (status IN ('PROPOSED', 'APPROVED', 'REJECTED', 'EXPIRED', 'APPLIED')),
  approved_by_user_id uuid REFERENCES users(id),
  approved_at timestamptz,
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (currency ~ '^[A-Z]{3}$'),
  CHECK (floor_amount <= recommended_amount AND recommended_amount <= ceiling_amount),
  CHECK (num_nonnulls(shipment_request_id, customer_quote_id, quote_option_id) >= 1),
  CHECK (expires_at > created_at)
);

CREATE INDEX ix_price_recommendations_context
  ON price_recommendations (quote_option_id, status, created_at DESC);

CREATE TABLE dynamic_pricing_policies (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code text NOT NULL UNIQUE,
  name text NOT NULL,
  service_definition_id uuid REFERENCES service_definitions(id),
  destination_country char(2),
  destination_province_state text,
  destination_city text,
  priority integer NOT NULL DEFAULT 100,
  minimum_margin_percent numeric(9,4) NOT NULL,
  maximum_discount_percent numeric(9,4) NOT NULL DEFAULT 0 CHECK (maximum_discount_percent BETWEEN 0 AND 100),
  maximum_surcharge_percent numeric(9,4) NOT NULL DEFAULT 0 CHECK (maximum_surcharge_percent BETWEEN 0 AND 100),
  require_human_approval_above_percent numeric(9,4) NOT NULL DEFAULT 0 CHECK (require_human_approval_above_percent BETWEEN 0 AND 100),
  rule_set jsonb NOT NULL,
  status text NOT NULL DEFAULT 'DRAFT'
    CHECK (status IN ('DRAFT', 'SHADOW', 'ACTIVE', 'PAUSED', 'RETIRED')),
  effective_from timestamptz,
  effective_until timestamptz,
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  approved_by_user_id uuid REFERENCES users(id),
  approved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (destination_country IS NULL OR destination_country ~ '^[A-Z]{2}$'),
  CHECK (effective_until IS NULL OR effective_from IS NULL OR effective_until >= effective_from)
);

CREATE INDEX ix_dynamic_pricing_policy_match
  ON dynamic_pricing_policies (service_definition_id, destination_country, destination_city, priority)
  WHERE status IN ('SHADOW', 'ACTIVE');

CREATE TABLE pricing_decisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  quote_option_id uuid NOT NULL REFERENCES quote_options(id),
  policy_id uuid REFERENCES dynamic_pricing_policies(id),
  recommendation_id uuid REFERENCES price_recommendations(id),
  decision_mode text NOT NULL
    CHECK (decision_mode IN ('RULES', 'AI_ASSISTED', 'MANUAL')),
  base_sell_amount numeric(18,4) NOT NULL CHECK (base_sell_amount >= 0),
  adjustment_amount numeric(18,4) NOT NULL,
  final_sell_amount numeric(18,4) NOT NULL CHECK (final_sell_amount >= 0),
  cost_amount numeric(18,4) NOT NULL CHECK (cost_amount >= 0),
  currency char(3) NOT NULL,
  resulting_margin_percent numeric(9,4) NOT NULL,
  input_snapshot jsonb NOT NULL,
  applied_factors jsonb NOT NULL DEFAULT '[]'::jsonb,
  guardrail_results jsonb NOT NULL,
  approval_status text NOT NULL DEFAULT 'NOT_REQUIRED'
    CHECK (approval_status IN ('NOT_REQUIRED', 'PENDING', 'APPROVED', 'REJECTED')),
  approved_by_user_id uuid REFERENCES users(id),
  approved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (currency ~ '^[A-Z]{3}$'),
  CHECK (final_sell_amount = base_sell_amount + adjustment_amount)
);

CREATE INDEX ix_pricing_decisions_option ON pricing_decisions (quote_option_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- Reliable messaging, webhooks, notifications, idempotency, and audit
-- ---------------------------------------------------------------------------

CREATE TABLE outbox_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  aggregate_type text NOT NULL,
  aggregate_id uuid NOT NULL,
  event_type text NOT NULL,
  event_version integer NOT NULL DEFAULT 1 CHECK (event_version > 0),
  correlation_id uuid,
  causation_id uuid,
  organization_id uuid REFERENCES organizations(id),
  payload jsonb NOT NULL,
  headers jsonb NOT NULL DEFAULT '{}'::jsonb,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  available_at timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz,
  publish_attempts integer NOT NULL DEFAULT 0 CHECK (publish_attempts >= 0),
  last_error text,
  locked_by text,
  locked_until timestamptz
);

CREATE INDEX ix_outbox_events_pending
  ON outbox_events (available_at, occurred_at)
  WHERE published_at IS NULL;

CREATE TABLE inbox_messages (
  consumer_name text NOT NULL,
  message_id uuid NOT NULL,
  event_type text NOT NULL,
  event_version integer NOT NULL CHECK (event_version > 0),
  payload_hash char(64) NOT NULL,
  received_at timestamptz NOT NULL DEFAULT now(),
  processed_at timestamptz,
  status text NOT NULL DEFAULT 'PROCESSING'
    CHECK (status IN ('PROCESSING', 'PROCESSED', 'FAILED', 'DEAD_LETTER')),
  attempt_count integer NOT NULL DEFAULT 1 CHECK (attempt_count > 0),
  last_error text,
  PRIMARY KEY (consumer_name, message_id),
  CHECK (payload_hash ~ '^[0-9a-f]{64}$')
);

CREATE INDEX ix_inbox_messages_failed
  ON inbox_messages (consumer_name, status, received_at)
  WHERE status IN ('FAILED', 'DEAD_LETTER');

CREATE TABLE webhook_subscriptions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  name text NOT NULL,
  endpoint_url text NOT NULL,
  encrypted_signing_secret text NOT NULL,
  secret_key_ref text NOT NULL,
  subscribed_event_types text[] NOT NULL,
  status text NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE', 'PAUSED', 'DISABLED')),
  consecutive_failure_count integer NOT NULL DEFAULT 0 CHECK (consecutive_failure_count >= 0),
  last_success_at timestamptz,
  last_failure_at timestamptz,
  created_by_user_id uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, name),
  CHECK (endpoint_url ~ '^https://')
);

CREATE TABLE webhook_deliveries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  subscription_id uuid NOT NULL REFERENCES webhook_subscriptions(id),
  outbox_event_id uuid NOT NULL REFERENCES outbox_events(id),
  attempt_number integer NOT NULL CHECK (attempt_number > 0),
  idempotency_key text NOT NULL UNIQUE,
  status text NOT NULL DEFAULT 'QUEUED'
    CHECK (status IN ('QUEUED', 'SENDING', 'SUCCEEDED', 'RETRY_WAIT', 'FAILED', 'DEAD_LETTER')),
  request_headers jsonb NOT NULL DEFAULT '{}'::jsonb,
  response_status integer,
  response_body_excerpt text,
  next_attempt_at timestamptz,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (subscription_id, outbox_event_id, attempt_number),
  CHECK (response_status IS NULL OR response_status BETWEEN 100 AND 599)
);

CREATE INDEX ix_webhook_deliveries_retry
  ON webhook_deliveries (next_attempt_at)
  WHERE status IN ('QUEUED', 'RETRY_WAIT');

CREATE TABLE notifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid REFERENCES organizations(id),
  recipient_user_id uuid REFERENCES users(id),
  recipient_address text,
  channel text NOT NULL
    CHECK (channel IN ('IN_APP', 'EMAIL', 'WEBHOOK')),
  template_code text NOT NULL,
  subject text,
  payload jsonb NOT NULL,
  status text NOT NULL DEFAULT 'QUEUED'
    CHECK (status IN ('QUEUED', 'SENDING', 'SENT', 'DELIVERED', 'READ', 'FAILED', 'CANCELLED')),
  idempotency_key text NOT NULL UNIQUE,
  scheduled_at timestamptz NOT NULL DEFAULT now(),
  sent_at timestamptz,
  delivered_at timestamptz,
  read_at timestamptz,
  error_code text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (recipient_user_id IS NOT NULL OR recipient_address IS NOT NULL)
);

CREATE INDEX ix_notifications_queue
  ON notifications (scheduled_at) WHERE status = 'QUEUED';
CREATE INDEX ix_notifications_user
  ON notifications (recipient_user_id, created_at DESC) WHERE recipient_user_id IS NOT NULL;

CREATE TABLE idempotency_records (
  organization_id uuid NOT NULL REFERENCES organizations(id),
  idempotency_key text NOT NULL,
  request_method text NOT NULL,
  request_path text NOT NULL,
  request_hash char(64) NOT NULL,
  response_status integer,
  response_body jsonb,
  resource_type text,
  resource_id uuid,
  status text NOT NULL DEFAULT 'PROCESSING'
    CHECK (status IN ('PROCESSING', 'COMPLETED', 'FAILED')),
  locked_until timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  PRIMARY KEY (organization_id, idempotency_key),
  CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  CHECK (response_status IS NULL OR response_status BETWEEN 100 AND 599),
  CHECK (expires_at > created_at)
);

CREATE INDEX ix_idempotency_records_expiry ON idempotency_records (expires_at);

CREATE TABLE audit_logs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  occurred_at timestamptz NOT NULL DEFAULT now(),
  organization_id uuid REFERENCES organizations(id),
  actor_user_id uuid REFERENCES users(id),
  actor_api_client_id uuid REFERENCES api_clients(id),
  actor_type text NOT NULL
    CHECK (actor_type IN ('USER', 'API_CLIENT', 'SYSTEM', 'SUPPORT')),
  action text NOT NULL,
  module text NOT NULL,
  entity_type text NOT NULL,
  entity_id uuid,
  correlation_id uuid,
  request_id text,
  ip_address inet,
  before_data jsonb,
  after_data jsonb,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  CHECK (
    (actor_type = 'USER' AND actor_user_id IS NOT NULL) OR
    (actor_type = 'API_CLIENT' AND actor_api_client_id IS NOT NULL) OR
    (actor_type IN ('SYSTEM', 'SUPPORT'))
  )
);

CREATE INDEX ix_audit_logs_entity ON audit_logs (entity_type, entity_id, occurred_at DESC);
CREATE INDEX ix_audit_logs_actor ON audit_logs (actor_user_id, occurred_at DESC);
CREATE INDEX ix_audit_logs_correlation ON audit_logs (correlation_id) WHERE correlation_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Read models/views. They are rebuildable and do not own business state.
-- ---------------------------------------------------------------------------

CREATE VIEW v_consolidation_pool_capacity AS
SELECT
  p.id AS consolidation_pool_id,
  p.pool_number,
  p.status,
  p.destination_city,
  p.planned_close_at,
  p.target_volume_cbm,
  p.target_weight_kg,
  COALESCE(sum(m.committed_volume_cbm) FILTER (
    WHERE m.status IN ('RESERVED', 'CONFIRMED')
  ), 0::numeric) AS committed_volume_cbm,
  COALESCE(sum(m.committed_weight_kg) FILTER (
    WHERE m.status IN ('RESERVED', 'CONFIRMED')
  ), 0::numeric) AS committed_weight_kg,
  GREATEST(
    p.target_volume_cbm - COALESCE(sum(m.committed_volume_cbm) FILTER (
      WHERE m.status IN ('RESERVED', 'CONFIRMED')
    ), 0::numeric),
    0::numeric
  ) AS remaining_target_volume_cbm,
  GREATEST(
    p.target_weight_kg - COALESCE(sum(m.committed_weight_kg) FILTER (
      WHERE m.status IN ('RESERVED', 'CONFIRMED')
    ), 0::numeric),
    0::numeric
  ) AS remaining_target_weight_kg
FROM consolidation_pools p
LEFT JOIN consolidation_pool_memberships m
  ON m.consolidation_pool_id = p.id
GROUP BY p.id;

CREATE VIEW v_supplier_current_kpis AS
SELECT DISTINCT ON (supplier_organization_id)
  supplier_organization_id,
  window_start,
  window_end,
  calculated_at,
  response_rate,
  win_rate,
  fulfillment_rate,
  complaint_rate,
  average_profit_amount,
  profit_currency,
  average_quote_response_minutes,
  rfq_count,
  quote_count,
  order_count,
  complaint_count,
  metric_version
FROM supplier_kpi_snapshots
ORDER BY supplier_organization_id, calculated_at DESC;

CREATE VIEW v_shipment_timeline AS
SELECT
  m.shipment_id,
  'MILESTONE'::text AS timeline_type,
  m.id AS timeline_id,
  m.milestone_code AS event_code,
  m.label,
  COALESCE(m.actual_at, m.estimated_at, m.planned_at, m.created_at) AS occurred_or_expected_at,
  m.status,
  m.location_id,
  NULL::text AS message
FROM tracking_milestones m
UNION ALL
SELECT
  e.shipment_id,
  'EVENT'::text AS timeline_type,
  e.id AS timeline_id,
  e.event_code,
  e.event_label AS label,
  e.occurred_at AS occurred_or_expected_at,
  COALESCE(e.event_status, 'RECORDED') AS status,
  e.location_id,
  e.message
FROM tracking_events e;

CREATE VIEW v_current_price_forecasts AS
SELECT DISTINCT ON (segment_key, horizon_days, target_date)
  id,
  model_id,
  segment_key,
  service_definition_id,
  destination_province_state,
  destination_city,
  horizon_days,
  target_date,
  currency,
  p10_amount,
  p50_amount,
  p90_amount,
  confidence,
  observation_count,
  training_cutoff_at,
  generated_at,
  expires_at
FROM price_forecasts
WHERE expires_at > now()
ORDER BY segment_key, horizon_days, target_date, generated_at DESC;

-- ---------------------------------------------------------------------------
-- Updated-at and append-only enforcement
-- ---------------------------------------------------------------------------

DO $$
DECLARE
  table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'organizations',
    'users',
    'organization_memberships',
    'roles',
    'api_clients',
    'integration_connections',
    'locations',
    'ai_runs',
    'review_tasks',
    'async_operations',
    'service_categories',
    'service_definitions',
    'service_relationships',
    'supplier_profiles',
    'supplier_contacts',
    'supplier_certifications',
    'facilities',
    'supplier_service_offerings',
    'supplier_service_coverages',
    'shipment_requests',
    'shipment_cargo_items',
    'logistics_plans',
    'plan_legs',
    'rfqs',
    'rfq_invitations',
    'supplier_quotes',
    'quote_parse_runs',
    'customer_quotes',
    'orders',
    'consolidation_pools',
    'consolidation_pool_memberships',
    'shipments',
    'fulfillment_tasks',
    'tracking_milestones',
    'supplier_complaints',
    'dynamic_pricing_policies',
    'webhook_subscriptions',
    'notifications'
  ]
  LOOP
    EXECUTE format('CREATE TRIGGER set_updated_at BEFORE UPDATE ON marketplace.%I FOR EACH ROW EXECUTE FUNCTION marketplace.set_updated_at()', table_name);
  END LOOP;
END;
$$;

CREATE TRIGGER audit_logs_append_only
  BEFORE UPDATE OR DELETE ON audit_logs
  FOR EACH ROW EXECUTE FUNCTION marketplace.reject_mutation();

CREATE TRIGGER tracking_events_append_only
  BEFORE UPDATE OR DELETE ON tracking_events
  FOR EACH ROW EXECUTE FUNCTION marketplace.reject_mutation();

CREATE TRIGGER price_observations_append_only
  BEFORE UPDATE OR DELETE ON price_observations
  FOR EACH ROW EXECUTE FUNCTION marketplace.reject_mutation();

CREATE TRIGGER task_status_history_append_only
  BEFORE UPDATE OR DELETE ON fulfillment_task_status_history
  FOR EACH ROW EXECUTE FUNCTION marketplace.reject_mutation();

CREATE TRIGGER supplier_kpi_snapshots_append_only
  BEFORE UPDATE OR DELETE ON supplier_kpi_snapshots
  FOR EACH ROW EXECUTE FUNCTION marketplace.reject_mutation();

COMMIT;
