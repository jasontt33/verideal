# Add `aging_report` Database to query-mcp — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the `aging-report` Postgres into the existing config-driven query-mcp as a third database alongside `ap_dashboard` and `pcard`.

**Architecture:** Three small edits to `query-mcp` (config + env + compose passthrough), one tiny edit to `aging-report` exposing its `db` service on a parameterized host port, and one deploy step on the EC2 to set the env vars and restart both stacks. No code changes to `server.py` — `_load_databases()` already picks up any new `config.yaml` entry.

**Tech Stack:** Python (FastMCP), Postgres 16, docker-compose, env-var-driven config.

**Spec:** [`docs/superpowers/specs/2026-06-09-add-aging-report-database-design.md`](../specs/2026-06-09-add-aging-report-database-design.md)

**Two repos involved:**
- `query-mcp` — this repo
- `aging-report` — sibling repo at `/Users/jay-t/stand-together/git/aging-report/`

There is no automated test suite in either repo. Verification is end-to-end via Docker Compose, `psql`, and an MCP tool call.

---

## Task 1: Expose aging-report's Postgres on a host port

**Repo:** `aging-report`

**Files:**
- Modify: `docker-compose.yml` (the `db:` service, around lines 6–23 in the current commit)
- Modify: `.env.example` (add the new variable so devs know it exists)

The aging-report `db` service currently has *no* host port binding ("No host port binding — the api reaches db over the compose network"). We add a parameterized binding so query-mcp (host networking) can reach Postgres at `localhost:<DB_HOST_PORT>`. Default is `5434` (the next port after pcard's `5433`).

- [ ] **Step 1: Add the port binding to the `db` service**

In `docker-compose.yml`, inside the `db:` service block, add a `ports:` key. Place it just before the existing `healthcheck:` key (preserves existing indentation and ordering).

```yaml
  db:
    image: postgres:16-alpine
    restart: unless-stopped
    networks: [aging]
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-aging}
      POSTGRES_USER: ${POSTGRES_USER:-aging}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-aging}
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./api/schema.sql:/docker-entrypoint-initdb.d/01-schema.sql:ro
    # Host port binding lets the sibling query-mcp container (which uses
    # network_mode: host) reach this db at localhost:${DB_HOST_PORT}. The
    # api still talks to db over the compose network using the service name.
    ports:
      - "${DB_HOST_PORT:-5434}:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-aging} -d ${POSTGRES_DB:-aging}"]
      interval: 5s
      timeout: 5s
      retries: 10
```

- [ ] **Step 2: Document the new env var in `.env.example`**

Append to `aging-report/.env.example`:

```
# Host port to expose Postgres on so sibling host-networked containers
# (e.g. query-mcp) can reach it at localhost:<DB_HOST_PORT>. The api
# itself does not use this — it talks to db over the compose network.
DB_HOST_PORT=5434
```

- [ ] **Step 3: Verify the compose file is syntactically valid**

Run from `aging-report/`:

```bash
docker compose config --quiet && echo "OK"
```

Expected: `OK` and exit 0. (No actual containers started.)

- [ ] **Step 4: Local smoke test — bring up `db` and confirm host port is reachable**

Run from `aging-report/`:

```bash
docker compose up -d db
# Wait for healthcheck to pass (up to ~30s)
for i in {1..15}; do
  if docker compose ps --format json db | grep -q '"Health":"healthy"'; then
    echo "db healthy"; break
  fi
  sleep 2
done
# Verify the host port answers
nc -zv localhost 5434 || (echo "port not reachable" && exit 1)
```

Expected: `db healthy` then `Connection to localhost port 5434 [tcp/*] succeeded!`

If port 5434 is already in use on your dev machine, set `DB_HOST_PORT=<some-other-free-port>` in `aging-report/.env`, re-run `docker compose up -d db`, and re-run the `nc -zv` with that port.

- [ ] **Step 5: Tear down the test container**

```bash
docker compose down
```

- [ ] **Step 6: Commit (in the `aging-report` repo)**

```bash
cd /Users/jay-t/stand-together/git/aging-report
git add docker-compose.yml .env.example
git commit -m "Expose db port to host via DB_HOST_PORT for sibling query-mcp"
```

---

## Task 2: Register `aging_report` in query-mcp config

**Repo:** `query-mcp`

**Files:**
- Modify: `config.yaml`
- Modify: `.env.example`
- Modify: `docker-compose.yml`

The MCP is config-driven. Adding a third database means appending one entry to `config.yaml`, one env var to `.env.example`, and one passthrough to `docker-compose.yml`. `server.py` is not touched.

- [ ] **Step 1: Append the `aging_report` entry to `config.yaml`**

Open `config.yaml`. Append (preserving the existing two entries unchanged):

```yaml
  - name: aging_report
    env_var: AGING_REPORT_DB_URL
    description: >
      AP "Days Aging" snapshots from Concur exports. Every weekly xlsx upload
      is preserved as a separate snapshot (uploads table); invoices are not
      upserted — each upload has its own full set of rows. Key tables:
      invoices (req_id, employee, supplier, total, days_aging, status,
      bucket), uploads (snapshot_date, label), exclusions (rows skipped at
      parse time), alert_actions (per-employee follow-up state, keyed by
      email), notifications_sent (Email/Teams audit log), roster
      (employee→company/dept/cost-center, bulk-replaced), vendor_notes,
      invoice_issues. When querying invoices, you almost always want to
      filter by upload_id (the snapshot) — typically the most recent.
      Ignore uploads.file_bytes (raw xlsx).
```

After the edit, the full `config.yaml` should look like:

```yaml
databases:
  - name: ap_dashboard
    env_var: AP_DASHBOARD_DB_URL
    description: >
      AP (Accounts Payable) invoice data from SAGE exports. Contains invoices,
      hold lists, vendor payment history, and PDF receipt check results.
      Key tables: invoices, holds, uploads, invoice_notes, attachments.

  - name: pcard
    env_var: PCARD_DB_URL
    description: >
      Purchase card (P-card) transaction data populated from spreadsheet uploads.
      Tracks employee spending, flags policy violations such as prohibited vendor
      categories (e.g. Uber Black), and stores suspicious transaction records.

  - name: aging_report
    env_var: AGING_REPORT_DB_URL
    description: >
      AP "Days Aging" snapshots from Concur exports. Every weekly xlsx upload
      is preserved as a separate snapshot (uploads table); invoices are not
      upserted — each upload has its own full set of rows. Key tables:
      invoices (req_id, employee, supplier, total, days_aging, status,
      bucket), uploads (snapshot_date, label), exclusions (rows skipped at
      parse time), alert_actions (per-employee follow-up state, keyed by
      email), notifications_sent (Email/Teams audit log), roster
      (employee→company/dept/cost-center, bulk-replaced), vendor_notes,
      invoice_issues. When querying invoices, you almost always want to
      filter by upload_id (the snapshot) — typically the most recent.
      Ignore uploads.file_bytes (raw xlsx).
```

- [ ] **Step 2: Append `AGING_REPORT_DB_URL` to `.env.example`**

At the end of `.env.example` add:

```
# aging_report: port is whatever DB_HOST_PORT is set to on the aging-report
# compose (default 5434 locally; may differ on the EC2).
AGING_REPORT_DB_URL=postgresql://aging:<aging_password>@localhost:5434/aging
```

- [ ] **Step 3: Add the env passthrough in `docker-compose.yml`**

In the `environment:` block of the `mcp` service, append one line after the existing `PCARD_DB_URL` line:

```yaml
      AGING_REPORT_DB_URL: ${AGING_REPORT_DB_URL}
```

After the edit, the full `environment:` block should read:

```yaml
    environment:
      MCP_PORT: ${MCP_PORT:-8502}
      MCP_API_KEY: ${MCP_API_KEY}
      MCP_JWT_SIGNING_KEY: ${MCP_JWT_SIGNING_KEY}
      PUBLIC_URL: ${PUBLIC_URL:-https://ap-dashboard.dev.standtogether.org}
      AP_DASHBOARD_DB_URL: ${AP_DASHBOARD_DB_URL}
      PCARD_DB_URL: ${PCARD_DB_URL}
      AGING_REPORT_DB_URL: ${AGING_REPORT_DB_URL}
```

- [ ] **Step 4: Verify the compose file is syntactically valid**

Run from `query-mcp/`:

```bash
docker compose config --quiet && echo "OK"
```

Expected: `OK` and exit 0.

- [ ] **Step 5: Verify `config.yaml` is valid YAML and the new entry is parseable**

Run from `query-mcp/`:

```bash
python3 -c "
import yaml
with open('config.yaml') as f:
    cfg = yaml.safe_load(f)
names = [d['name'] for d in cfg['databases']]
assert names == ['ap_dashboard', 'pcard', 'aging_report'], names
env_vars = [d['env_var'] for d in cfg['databases']]
assert 'AGING_REPORT_DB_URL' in env_vars, env_vars
print('OK:', names)
"
```

Expected: `OK: ['ap_dashboard', 'pcard', 'aging_report']`.

- [ ] **Step 6: Commit (in the `query-mcp` repo)**

```bash
cd /Users/jay-t/stand-together/git/query-mcp
git add config.yaml .env.example docker-compose.yml
git commit -m "Add aging_report database to query-mcp config"
```

---

## Task 3: Local end-to-end verification

**Repo:** both, run from `query-mcp/`

This task confirms the MCP actually loads the new database and that `list_databases` / `get_schema` / `run_query` work against it. Done locally before deploy.

- [ ] **Step 1: Make sure aging-report's stack is up locally with seed data**

Run from `aging-report/`:

```bash
cd /Users/jay-t/stand-together/git/aging-report
cp -n .env.example .env || true   # only if you don't already have one
docker compose up -d
# wait for db to be healthy
for i in {1..15}; do
  if docker compose ps --format json db | grep -q '"Health":"healthy"'; then
    echo "db healthy"; break
  fi
  sleep 2
done
```

The first boot will auto-apply `api/schema.sql` and seed the `exclusions` row.

- [ ] **Step 2: Confirm you can reach the aging db from the host**

```bash
PGPASSWORD=$(grep ^POSTGRES_PASSWORD /Users/jay-t/stand-together/git/aging-report/.env | cut -d= -f2) \
  psql -h localhost -p 5434 -U aging -d aging -c "\dt"
```

Expected: a table listing showing `uploads`, `invoices`, `exclusions`, `alert_actions`, `notifications_sent`, `roster`, `roster_meta`, `vendor_notes`, `invoice_issues`.

If your `aging-report/.env` set `DB_HOST_PORT` to something other than 5434, substitute that port here and everywhere else in this task.

- [ ] **Step 3: Configure query-mcp's local `.env`**

Run from `query-mcp/`:

```bash
cd /Users/jay-t/stand-together/git/query-mcp
cp -n .env.example .env || true
```

Then edit `.env` (manually, or via your editor) so `AGING_REPORT_DB_URL` points at the local aging db. Use the password from `aging-report/.env`:

```
AGING_REPORT_DB_URL=postgresql://aging:<paste-aging-password>@localhost:5434/aging
```

Also make sure `MCP_API_KEY` and `MCP_JWT_SIGNING_KEY` are set (any 32-byte hex is fine for local). If they aren't, generate them:

```bash
echo "MCP_API_KEY=$(openssl rand -hex 32)" >> .env
echo "MCP_JWT_SIGNING_KEY=$(openssl rand -hex 32)" >> .env
```

- [ ] **Step 4: Boot query-mcp and confirm it registers all three databases**

```bash
docker compose up -d --build
# Tail logs until we see the startup line
docker compose logs --tail=50 mcp | grep -E "Registered database|Starting ST Query MCP"
```

Expected (order is best-effort; all three lines should appear):

```
INFO  __main__  Registered database: ap_dashboard
INFO  __main__  Registered database: pcard
INFO  __main__  Registered database: aging_report
INFO  __main__  Starting ST Query MCP on port 8502  databases=['ap_dashboard', 'pcard', 'aging_report']
```

If `ap_dashboard` or `pcard` are missing locally because you don't have those Postgres instances running, that's fine — the goal here is that `aging_report` shows up. The MCP logs `WARNING ... Env var ... not set — skipping database 'X'` for any missing one; that's expected for the two you don't have running.

- [ ] **Step 5: Call the MCP and confirm the new database is queryable**

The MCP speaks JSON-RPC over HTTP at `POST /mcp` with a Bearer token. Easiest local check is via curl using the static `MCP_API_KEY`:

```bash
API_KEY=$(grep ^MCP_API_KEY /Users/jay-t/stand-together/git/query-mcp/.env | cut -d= -f2)

# List databases — should include aging_report
curl -s -X POST http://localhost:8502/mcp \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_databases","arguments":{}}}'
```

Expected: a JSON-RPC response whose `result.content[0].text` lists `aging_report` along with the description.

```bash
# Get schema for aging_report — should list invoices, uploads, etc.
curl -s -X POST http://localhost:8502/mcp \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_schema","arguments":{"database_name":"aging_report"}}}'
```

Expected: schema dump including `invoices`, `uploads`, `exclusions`, `alert_actions`, `notifications_sent`, `roster`, `roster_meta`, `vendor_notes`, `invoice_issues`.

```bash
# Run a trivial query against aging_report — should at least return the seed exclusion row
curl -s -X POST http://localhost:8502/mcp \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"run_query","arguments":{"database_name":"aging_report","sql":"SELECT count(*) FROM exclusions"}}}'
```

Expected: a row with `count` ≥ 1 (the seed `Ghost record` row makes this ≥ 1 on a fresh boot).

- [ ] **Step 6: Tear down local stacks**

```bash
cd /Users/jay-t/stand-together/git/query-mcp && docker compose down
cd /Users/jay-t/stand-together/git/aging-report && docker compose down
```

Note: do **not** use `-v` on aging-report's `down` unless you want to wipe local data. Leaving the volume preserves anything you uploaded for further testing.

- [ ] **Step 7: Push both branches**

```bash
cd /Users/jay-t/stand-together/git/aging-report
git push

cd /Users/jay-t/stand-together/git/query-mcp
git push
```

If either repo's branch needs a PR per your team's flow, open it now; otherwise these can merge directly to whatever the project's default branch is. The spec covers the *what*; the *how to merge* follows whatever the existing process for these two repos is.

---

## Task 4: Deploy to the EC2

**Repo:** the EC2 host itself (whatever directory the two compose stacks live in — typically `/data/aging-report/` and `/data/query-mcp/` based on the prior pattern; confirm before running).

This is the only step that touches a shared system. Do it deliberately. If unsure about anything below, **stop and ask before continuing** rather than guessing.

- [ ] **Step 1: SSH to the EC2 and locate the two deploy directories**

```bash
# On your laptop:
ssh <your-ec2-host>

# On the EC2:
sudo find /data -maxdepth 2 -type d \( -name 'aging-report*' -o -name 'query-mcp*' \) 2>/dev/null
```

Note the two paths. The following steps use `$AGING_DIR` and `$MCP_DIR` as placeholders — set them to the paths you found:

```bash
AGING_DIR=/data/aging-report   # adjust to actual
MCP_DIR=/data/query-mcp        # adjust to actual
```

- [ ] **Step 2: Check what host ports Postgres containers already use on the EC2**

```bash
sudo ss -ltnp | grep -E ':(5432|5433|5434|5435|5436)\b' || echo "none of 5432-5436 in use"
```

Pick a free port for aging-report. If 5434 is free, use 5434 (matches the spec default). If not, pick the next free one (5435, 5436, …). Record it:

```bash
AGING_PORT=5434   # or whatever you picked
```

- [ ] **Step 3: Pull the latest `aging-report` commit and set `DB_HOST_PORT`**

```bash
cd "$AGING_DIR"
sudo git fetch --all
sudo git pull --ff-only
# Append (or update) DB_HOST_PORT in the existing .env. Use a small idempotent script:
sudo grep -q '^DB_HOST_PORT=' .env \
  && sudo sed -i "s|^DB_HOST_PORT=.*|DB_HOST_PORT=${AGING_PORT}|" .env \
  || echo "DB_HOST_PORT=${AGING_PORT}" | sudo tee -a .env >/dev/null
sudo grep DB_HOST_PORT .env
```

Expected last line: `DB_HOST_PORT=<the port you chose>`.

- [ ] **Step 4: Restart aging-report and verify the binding**

```bash
cd "$AGING_DIR"
sudo docker compose up -d
sleep 5
sudo docker compose ps
sudo ss -ltn | grep ":${AGING_PORT}\b"
```

Expected: aging-report's `db`, `api`, `web` all "Up (healthy)" (or "Up"), and `ss` shows something LISTENing on `0.0.0.0:${AGING_PORT}` or `:::${AGING_PORT}`.

If you see another container or process already owning that port, stop here and pick a different port (back to Step 2).

- [ ] **Step 5: Get the aging Postgres password**

```bash
cd "$AGING_DIR"
sudo grep ^POSTGRES_PASSWORD .env
```

Copy the value (everything after the `=`) — you'll paste it into the next step.

- [ ] **Step 6: Pull the latest `query-mcp` commit and set `AGING_REPORT_DB_URL`**

```bash
cd "$MCP_DIR"
sudo git fetch --all
sudo git pull --ff-only

# Build the connection string with the password from step 5 and the port from step 2.
# Replace <PASTE_PASSWORD> below.
AGING_URL="postgresql://aging:<PASTE_PASSWORD>@localhost:${AGING_PORT}/aging"

# Append or update in .env
sudo grep -q '^AGING_REPORT_DB_URL=' .env \
  && sudo sed -i "s|^AGING_REPORT_DB_URL=.*|AGING_REPORT_DB_URL=${AGING_URL}|" .env \
  || echo "AGING_REPORT_DB_URL=${AGING_URL}" | sudo tee -a .env >/dev/null
sudo grep AGING_REPORT_DB_URL .env
```

Expected: a line `AGING_REPORT_DB_URL=postgresql://aging:...@localhost:<port>/aging`.

- [ ] **Step 7: Restart query-mcp and confirm it registers the new database**

```bash
cd "$MCP_DIR"
sudo docker compose up -d --build
sleep 5
sudo docker compose logs --tail=50 mcp | grep -E "Registered database|Starting ST Query MCP"
```

Expected: all three `Registered database:` lines, including `aging_report`, and a `Starting ST Query MCP ... databases=['ap_dashboard', 'pcard', 'aging_report']` line.

If `aging_report` is missing, check `sudo docker compose logs mcp | grep -i aging` — most likely the env var didn't make it in or the password is wrong. The container will log `WARNING ... Env var ... not set — skipping database 'aging_report'` if the var is empty.

- [ ] **Step 8: End-to-end smoke test via the public URL**

From your laptop (not the EC2). You need a valid Bearer token. Easiest: use the static `MCP_API_KEY` from `$MCP_DIR/.env`. **Do not paste this token into any public/shared terminal.**

```bash
# On the EC2, copy the API key to your clipboard somehow safe (or read it):
sudo grep ^MCP_API_KEY "$MCP_DIR/.env"
# Then on your laptop:
API_KEY="<paste>"
curl -s -X POST https://ap-dashboard.dev.standtogether.org/mcp \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_databases","arguments":{}}}'
```

Expected: a JSON-RPC response with `aging_report` listed in the text content.

- [ ] **Step 9: Confirm with an actual query against aging_report**

```bash
curl -s -X POST https://ap-dashboard.dev.standtogether.org/mcp \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"run_query","arguments":{"database_name":"aging_report","sql":"SELECT count(*) AS n FROM invoices"}}}'
```

Expected: a row count from the live `invoices` table (whatever the current snapshots add up to).

- [ ] **Step 10: Done — verify the MCP client (claude.ai) sees the new DB**

In whichever MCP client you normally use (claude.ai via OAuth), reload the connection and ask:

> "List the databases available via the ST query MCP."

The response should mention `aging_report` along with the description. If it doesn't, the client may be caching the old tool list — disconnect and reconnect the MCP integration.

---

## Self-review checklist

- [x] **Spec coverage:** Every change in the spec maps to a task — config.yaml entry (Task 2 Step 1), `.env.example` (Task 2 Step 2), query-mcp docker-compose (Task 2 Step 3), aging-report port binding (Task 1 Step 1), EC2 deploy (Task 4). The "what this does NOT do" items remain not done.
- [x] **No placeholders.** `<paste>` / `<PASTE_PASSWORD>` / `<your-ec2-host>` are intentional manual-input points, not engineering TODOs.
- [x] **Type consistency.** Env-var names (`DB_HOST_PORT`, `AGING_REPORT_DB_URL`), database slug (`aging_report`), and port (`5434` default, overridable) match across all tasks.
- [x] **No code changes to `server.py`.** Confirmed by re-reading `_load_databases()` — it iterates `cfg["databases"]` and skips entries whose env var is unset, so a new `config.yaml` entry plus env var is sufficient.
