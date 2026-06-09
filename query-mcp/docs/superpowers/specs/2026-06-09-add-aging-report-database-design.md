# Add `aging_report` database to query-mcp

**Date:** 2026-06-09
**Status:** Approved (pending implementation)

## Goal

Expose the `aging-report` app's Postgres to the existing query-mcp so the LLM can answer questions about AP "Days Aging" snapshots alongside `ap_dashboard` and `pcard`. No new auth, no new tools — just a third entry in the config-driven multi-database server.

## Background

`query-mcp` is config-driven: each database is one entry in `config.yaml` + one env var holding a connection string. The server (`server.py`) uses host networking on the EC2 and reaches each Postgres at `localhost:<port>`. Today:

- `ap_dashboard` → `localhost:5432` (ap_review_dashboard's compose)
- `pcard` → `localhost:5433` (p-card-dashboard's compose)

`aging-report` runs on the same EC2 via its own `docker-compose.yml`, but its `db` service has **no host port binding** — Postgres is only reachable on the `aging` bridge network. That's the one piece of plumbing we need to add.

## Design

### Repo: `query-mcp`

**1. `config.yaml`** — append:

```yaml
- name: aging_report
  env_var: AGING_REPORT_DB_URL
  description: >
    AP "Days Aging" snapshots from Concur exports. Every weekly xlsx upload is
    preserved as a separate snapshot (uploads table); invoices are not upserted —
    each upload has its own full set of rows. Key tables: invoices (req_id,
    employee, supplier, total, days_aging, status, bucket), uploads
    (snapshot_date, label), exclusions (rows skipped at parse time),
    alert_actions (per-employee follow-up state, keyed by email),
    notifications_sent (Email/Teams audit log), roster (employee→company/dept/
    cost-center, bulk-replaced), vendor_notes, invoice_issues. When querying
    invoices, you almost always want to filter by upload_id (the snapshot)
    — typically the most recent. Ignore uploads.file_bytes (raw xlsx).
```

**2. `.env.example`** — append:

```
# aging_report: host port is set on the aging-report compose via DB_HOST_PORT
AGING_REPORT_DB_URL=postgresql://aging:<aging_password>@localhost:5434/aging
```

**3. `docker-compose.yml`** — append one line under `environment:`:

```yaml
AGING_REPORT_DB_URL: ${AGING_REPORT_DB_URL}
```

No changes to `server.py`. The `_load_databases()` loop already picks up any new `config.yaml` entry whose env var is set.

### Repo: `aging-report`

**4. `docker-compose.yml`** — add a parameterized host-port binding to the `db` service:

```yaml
db:
  image: postgres:16-alpine
  ...
  ports:
    - "${DB_HOST_PORT:-5434}:5432"
```

Default `5434` so local dev (`docker compose up`) Just Works after this change. Production sets `DB_HOST_PORT` in the EC2's `.env` to whatever port is actually free there.

### Deploy (EC2)

1. Pull the new `aging-report` commit on the EC2. Set `DB_HOST_PORT=<free-port>` in `aging-report`'s `.env`. `docker compose up -d` to apply the binding. Confirm Postgres responds on `localhost:<DB_HOST_PORT>`.
2. Pull the new `query-mcp` commit on the EC2. Set `AGING_REPORT_DB_URL=postgresql://aging:<password>@localhost:<DB_HOST_PORT>/aging` in `query-mcp`'s `.env`. `docker compose up -d` to restart the MCP.
3. Verify: `list_databases` via the MCP should now include `aging_report`; `get_schema("aging_report")` should return the tables above.

## Non-goals

- **No column-level filtering.** `get_schema` will still surface `uploads.file_bytes`; we rely on the description to steer the LLM away. If this turns into a real problem in usage, revisit.
- **No app-level changes** to `aging-report`. It keeps using its internal `aging` bridge network for app→db traffic; we're only *additionally* exposing the db port to the host.
- **No new auth/scopes.** Same OAuth + Bearer JWT path, same Okta gating at the ALB. Anyone who can reach the MCP today can query the new DB.

## Risks & mitigations

- **Port collision on EC2 restart.** If the EC2's existing `.env` doesn't set `DB_HOST_PORT` and 5434 is already in use, `docker compose up` on aging-report will fail. → Set `DB_HOST_PORT` to a known-free port in the EC2's `.env` *before* restarting.
- **Sensitive data exposure via SQL.** The new DB contains employee emails, names, and follow-up notes. Same sensitivity tier as `ap_dashboard`; no extra control needed beyond the existing Okta gating. Worth being aware of.
- **`file_bytes` egress.** If the LLM ignores the description and does `SELECT * FROM uploads`, large BYTEA rows would flow through. The 500-row cap in `run_query` helps; tightening to a column-blocklist is the followup if this happens.

## Out of scope (future work)

- Column-level exclusion in `get_schema` / `run_query`.
- Per-database scopes in the OAuth flow.
- Adding `aging-report` as a separate MCP server instead of another database in this one (current pattern is one MCP, many DBs — keep it that way).
