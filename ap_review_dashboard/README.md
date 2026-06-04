# AP Review Dashboard

A web application for the Stand Together Accounts Payable team's daily payment
review. Upload the daily AP Payment spreadsheet, drill down by entity, manage
the hold list, flag and review large invoices, run spot checks, and add
reviewer notes / supporting attachments — all backed by Postgres so that
reviewer input persists across uploads and browser sessions.

This is a port of the original single-file `ap_review_dashboard.html` prototype
to a real web app with persistent storage, while preserving the original look
and feel.

---

## Stack

| Layer       | Choice                                                   |
| ----------- | -------------------------------------------------------- |
| Backend     | FastAPI (Python 3.12) on Uvicorn                         |
| ORM / DB    | SQLAlchemy 2.x + Postgres 16                             |
| Spreadsheet | openpyxl                                                 |
| Frontend    | Static HTML/CSS/JS (no build step), served by the backend |
| Packaging   | Docker + docker-compose                                  |

## Quick start

```bash
cp .env.example .env          # optional — defaults work
docker compose up --build
```

Then open <http://localhost:8000>.

The first request will lazily create the database schema. Use the **Upload New
Data** tab to load an `AP_Payments_*.xlsx` file; all other tabs refresh
automatically.

To stop and wipe data:

```bash
docker compose down -v        # -v also removes pgdata, uploads, attachments volumes
```

## Project layout

```
ap_review_dashboard/
├── docker-compose.yml
├── .env.example
├── ap_review_dashboard.html    # original single-file prototype (reference)
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   └── app/
│       ├── db.py               # SQLAlchemy engine + session
│       ├── models.py           # ORM tables
│       ├── parser.py           # xlsx ingest logic
│       └── main.py             # FastAPI app + static mount
├── frontend/
│   └── index.html              # the dashboard UI
└── backend/tests/              # pytest suite
```

## Configuration

All configuration is via environment variables (see `.env.example`):

| Variable            | Default        | Purpose                                |
| ------------------- | -------------- | -------------------------------------- |
| `POSTGRES_USER`     | `ap_user`      | Postgres user                          |
| `POSTGRES_PASSWORD` | `ap_password`  | Postgres password                      |
| `POSTGRES_DB`       | `ap_review`    | Database name                          |
| `POSTGRES_PORT`     | `5432`         | Host-side port mapped to db container  |
| `WEB_PORT`          | `8000`         | Host-side port for the web app         |
| `DATABASE_URL`      | (built in compose) | SQLAlchemy URL — overrides PG\_\* if set |
| `UPLOAD_DIR`        | `/data/uploads`     | Where uploaded spreadsheets are kept |
| `ATTACHMENT_DIR`    | `/data/attachments` | Where reviewer attachments are kept  |

## Data model

| Table             | Purpose                                                                     | Replaced on upload? |
| ----------------- | --------------------------------------------------------------------------- | ------------------- |
| `uploads`         | One row per ingested spreadsheet — the historical index                     | Appended            |
| `invoices`        | Invoice rows tagged with `upload_id` — every snapshot is preserved          | Appended            |
| `holds`           | Hold-list rows tagged with `upload_id` — every snapshot is preserved        | Appended            |
| `invoice_notes`   | Reviewer notes, keyed by `(org, bill)`                                      | **No** — global, survives uploads |
| `attachments`     | Manual file attachment metadata, keyed by `(org, bill)` (file on disk)      | **No** — global, survives uploads |

The dashboard defaults to the *latest* upload's invoices and holds. Every
prior upload remains in the database and can be browsed via the history
selector in the top-right of the navigation bar (or by passing
`?upload_id=N` to the API). Notes and attachments are joined onto invoices
by `(org, bill)`, so they appear consistently across every snapshot in
which that invoice appears.

## API reference

| Method | Path                                  | Description                          |
| ------ | ------------------------------------- | ------------------------------------ |
| GET    | `/api/health`                         | Liveness probe                       |
| POST   | `/api/upload`                         | Multipart `file=` — ingests `.xlsx`  |
| GET    | `/api/uploads`                        | Upload history, newest first         |
| GET    | `/api/invoices?upload_id=N`           | Invoices for one upload (default: latest) + joined notes/attachments |
| GET    | `/api/holds?upload_id=N`              | Hold list for one upload (default: latest) |
| PUT    | `/api/notes`                          | Upsert `{org, bill, note}`           |
| GET    | `/api/attachments?org=&bill=`         | List attachments for an invoice      |
| POST   | `/api/attachments?org=&bill=`         | Multipart `file=` — adds attachment  |
| GET    | `/api/attachments/{id}/download`      | Download an attachment               |
| DELETE | `/api/attachments/{id}`               | Delete an attachment                 |

Interactive docs: <http://localhost:8000/docs>.

## Running tests

The backend has a pytest suite covering the spreadsheet parser and the HTTP
API. Tests use an in-memory SQLite database — no Postgres required.

```bash
cd backend
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

Or inside Docker:

```bash
docker compose run --rm web sh -c "pip install -r requirements-dev.txt && pytest"
```

## Development

To iterate on the frontend without rebuilding the image: the `frontend/`
directory is bind-mounted into the `web` container, so edits to
`frontend/index.html` are picked up on the next browser refresh.

For backend changes, rebuild:

```bash
docker compose up --build web
```

## Operational notes

- Uploaded spreadsheets and attachments live in named Docker volumes
  (`uploads`, `attachments`). Back these up alongside `pgdata` if you care
  about long-term retention.
- The two SharePoint document links shown for `P-#####` bills are currently
  hard-coded in `frontend/index.html`. Move them to a config table if the
  list grows.
- This app has no authentication. Run it on a private network or put it
  behind a reverse proxy that handles SSO before exposing it.

See [`USERS_GUIDE.md`](USERS_GUIDE.md) for the end-user walkthrough.
