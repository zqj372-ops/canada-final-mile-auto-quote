# Hermes Ops Kit

This folder gives Hermes Agent a small, repeatable operating surface for the
Canada final-mile quote service. These scripts are intentionally read-only by
default. They help Hermes inspect health, logs, quote matching, manual tasks,
and learning candidates without inventing prices or touching secrets.

## Server Defaults

```text
Public URL: https://quote.freightclaw.net
Docker project: canada_quote_oracle
Compose file: infra/docker-compose.prod.yml
Env file: .env.prod
```

Override with environment variables when needed:

```bash
HERMES_PUBLIC_URL=https://quote.freightclaw.net \
HERMES_COMPOSE_PROJECT=canada_quote_oracle \
HERMES_COMPOSE_FILE=infra/docker-compose.prod.yml \
HERMES_ENV_FILE=.env.prod \
ops/hermes/scripts/check_health.sh
```

## Common Commands

```bash
ops/hermes/scripts/check_health.sh
ops/hermes/scripts/check_recent_errors.sh 80
ops/hermes/scripts/check_manual_tasks.sh
ops/hermes/scripts/check_hermes_diagnostics.sh pending 20
ops/hermes/scripts/check_learning_candidates.sh
ops/hermes/scripts/check_zone_match.sh S7K Saskatoon SK
ops/hermes/scripts/quote_debug_snapshot.sh <quote_id>
ops/hermes/run_daily_report.sh
```

## Hermes Rules

- Do not calculate or change freight prices.
- Do not print API keys, SMTP passwords, webhook URLs, or decrypted secrets.
- Diagnose pricing issues from deterministic data first:
  `postal_code_city_lookup`, `zone_lookup_rules`, `zone_price_matrix`,
  `quote_rule_config`, `learned_quote_rules`.
- If a price is missing, explain why and point to the manual task or learning
  candidate path. Do not invent a fallback price.
- Read `hermes_diagnostic_queue` before proposing a correction. It contains
  the compact diagnostic package: raw input, parsed result, address, zone hit,
  price matrix, failure reason, neighboring FSA, manual history, and private
  reference context.
- A Hermes suggestion is advisory only. A resolved manual task is still
  required before a learning candidate can be approved and reused.
- Prefer these scripts before ad-hoc SQL.

## Model selection

The backoffice AI settings page can bind one encrypted model configuration to
the built-in Hermes diagnostic path. This binding is independent from the
default AI quote extraction model. If no Hermes configuration is selected, the
application falls back to the enabled general default model.
