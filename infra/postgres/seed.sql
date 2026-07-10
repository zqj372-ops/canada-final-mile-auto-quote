INSERT INTO vendor_rate_rules (
    rule_id,
    source_type,
    origin_warehouse,
    vendor_name,
    province,
    city,
    fsa,
    postal_code,
    pallet_min,
    pallet_max,
    weight_min_kg,
    weight_max_kg,
    base_cost_cad,
    fuel_percent,
    appointment_fee_cad,
    liftgate_fee_cad,
    residential_fee_cad,
    limited_access_fee_cad,
    remote_fee_cad,
    status
) VALUES
    (
        'demo-fsa-l5t-1-3',
        'fsa',
        'Toronto',
        'Demo Carrier',
        'ON',
        'Mississauga',
        'L5T',
        NULL,
        1,
        3,
        NULL,
        1500,
        120.00,
        12.50,
        25.00,
        45.00,
        35.00,
        0.00,
        0.00,
        'active'
    ),
    (
        'demo-fsa-l4k-1-3',
        'fsa',
        'Toronto',
        'Demo Carrier',
        'ON',
        'Concord',
        'L4K',
        NULL,
        1,
        3,
        NULL,
        1500,
        135.00,
        12.50,
        25.00,
        45.00,
        35.00,
        0.00,
        0.00,
        'active'
    ),
    (
        'demo-fsa-v6v-1-3',
        'fsa',
        'Vancouver',
        'Demo Carrier',
        'BC',
        'Richmond',
        'V6V',
        NULL,
        1,
        3,
        NULL,
        1500,
        145.00,
        12.50,
        25.00,
        45.00,
        35.00,
        0.00,
        0.00,
        'active'
    ),
    (
        'demo-postal-l4k2n2',
        'postal_code',
        'Toronto',
        'Demo Carrier',
        'ON',
        'Concord',
        'L4K',
        'L4K 2N2',
        1,
        3,
        NULL,
        1500,
        128.00,
        12.50,
        25.00,
        45.00,
        35.00,
        0.00,
        0.00,
        'active'
    ),
    (
        'demo-inactive-l5t',
        'fsa',
        'Toronto',
        'Demo Carrier',
        'ON',
        'Mississauga',
        'L5T',
        NULL,
        1,
        3,
        NULL,
        1500,
        90.00,
        12.50,
        25.00,
        45.00,
        35.00,
        0.00,
        0.00,
        'inactive'
    )
ON CONFLICT (rule_id) DO NOTHING;

INSERT INTO postal_code_city_lookup (postal_code, preferred_city, province) VALUES
    ('L4K 2N2', 'Concord', 'ON'),
    ('V6V 1A1', 'Richmond', 'BC'),
    ('T1X 0A0', 'Calgary', 'AB')
ON CONFLICT (postal_code) DO NOTHING;

INSERT INTO zone_lookup_rules (
    postal_prefix,
    city,
    province,
    origin,
    zone,
    match_level,
    note
) VALUES
    ('L4K', 'CONCORD', 'ON', 'toronto', 2, 'demo', 'Demo L4K Concord rule'),
    ('V6V', 'RICHMOND', 'BC', 'toronto', 5, 'demo', 'Demo stale BC origin for override test'),
    ('T1X', 'CALGARY', 'AB', 'calgary', 1, 'demo', 'Demo split record'),
    ('T1X', 'CALGARY', 'AB', 'toronto', 9, 'demo', 'Demo split record conflict')
ON CONFLICT DO NOTHING;

INSERT INTO zone_price_matrix (
    origin,
    zone,
    billing_pallets,
    base_price_usd,
    source,
    last_updated
) VALUES
    ('toronto', 2, 1, 90.00, 'demo seed', '2026-06-03'),
    ('toronto', 2, 2, 105.00, 'demo seed', '2026-06-03'),
    ('toronto', 2, 3, 120.00, 'demo seed', '2026-06-03'),
    ('toronto', 2, 4, 135.00, 'demo seed', '2026-06-03'),
    ('calgary', 5, 3, 180.00, 'demo seed', '2026-06-03'),
    ('calgary', 1, 3, 100.00, 'demo seed', '2026-06-03')
ON CONFLICT (origin, zone, billing_pallets) DO NOTHING;

INSERT INTO quote_rule_config (key, value, description) VALUES
    ('fuel_percent', '35', 'Zone matrix fuel surcharge percent.'),
    ('residential_fee_usd', '50', 'Residential/private/rural residential accessorial fee.'),
    ('liftgate_fee_usd', '50', 'Liftgate accessorial fee when requested.'),
    ('pallet_jack_fee_usd', '50', 'Pallet jack accessorial fee when requested.'),
    ('appointment_fee_usd', '50', 'Appointment accessorial fee when requested.'),
    ('detention_half_hour_fee_usd', '35', 'Detention fee after the free 30 minutes.')
ON CONFLICT (key) DO NOTHING;
