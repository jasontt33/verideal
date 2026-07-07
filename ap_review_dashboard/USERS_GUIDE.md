# AP Review Dashboard — User's Guide

This guide walks through using the AP Review Dashboard for the daily Accounts
Payable review.

---

## Opening the dashboard

Browse to the URL your team has set up (e.g. <http://localhost:8000> for a
local install). The header shows today's date and the data-source banner under
the **Payment Summary** tab tells you which spreadsheet is currently loaded
and when it was uploaded.

If you see *"No data uploaded yet"*, jump to the [Uploading data](#uploading-the-daily-ap-file)
section first.

## The five tabs

### 📊 Payment Summary

Your starting point. Shows four KPI cards and an entity-level table.

**KPIs**

- **Total Payments** — number of invoices in the batch
- **Total Amount** — sum of all invoice amounts pending disbursement
- **On Hold** — count of invoices flagged on the hold list
- **Entities on File** — distinct organizations in the batch

**Entity Payment Summary table**

Each row is one entity (e.g. "Americans for Prosperity"). Columns:

- **Invoices** — count for that entity
- **Total Amount** — entity total
- **% of Batch** — that entity's share of the overall batch, with a bar
- **Hold Status** — green ✓ Clear, or orange ⚠ N on hold
- **Actions** — **View Invoices ▾** opens a drilldown modal

**Drilldown modal** — click **View Invoices** on any row.

You'll see the entity's invoices listed individually. Each invoice card shows:

- Vendor, reference, bill #, dates, amount
- A red banner if the invoice is on hold (with the hold reason and ticket #)
- W-9 type and status
- A SharePoint link if the bill # contains a `P-#####` and that document has
  been mapped
- A **Manual Attachments** section — see [Attachments](#attachments) below
- A **Reviewer Notes** text box — see [Notes](#notes) below

### ⚠️ Hold List

A vendor-by-vendor view of every invoice currently on hold. Each card shows
the entity, vendor, hold reason, ticket number (e.g. `P2P-11084`), the amount
held, and the most recent status note from the parsed Hold List sheet.

The header KPIs summarize: how many vendors are blocked, the total dollars on
hold, and how many entities are affected.

### 💰 >$100K Invoices

A filtered table of any single invoices ≥ $100,000. Use this to make sure
large payments get extra eyes. Notes and attachments edited here sync with the
same invoice elsewhere — they're keyed by entity + bill #.

If there are no invoices over the threshold, you'll see a friendly empty state.

### 🔍 Spot Check

Picks 3 random invoices from 3 different entities for a QA sample. Excludes
holds and excludes invoices over $100K (those are reviewed by their dedicated
tab). Click **🔄 Re-run Spot Check** to draw a new random sample.

The criteria table below documents the standard checks you should run on each
spot-checked invoice.

### 📁 Upload New Data

How you load a new daily spreadsheet — see the next section.

## Uploading the daily AP file

1. Open the **Upload New Data** tab.
2. Drag and drop your `AP_Payments_MM_DD_YY.xlsx` into the dashed box, or
   click **Choose File**.
3. The page shows progress, then a green confirmation with the invoice and
   hold counts. All other tabs refresh immediately.

**What gets ingested:**

- The first sheet whose name contains "AP" or "Dashboard" (or, failing that,
  the first sheet in the workbook) is parsed as the **invoice list**.
- Any sheet whose name contains "Hold" is parsed as the **hold list**.
- The parser is tolerant of column ordering and uses fuzzy header matching
  (e.g. "Bill Number" / "Bill #" / "Bill" all map to the same field).
- Rows like `Sum for X`, `Sum Total`, `Grand Total`, and entity-header rows
  with no vendor are ignored automatically.
- Holds are cross-referenced against invoices by vendor name; matching
  invoices are flagged with the on-hold red banner everywhere.

**Important:** Your reviewer notes and manual attachments are keyed by entity +
bill #, so they automatically reconnect to the same invoice in the next day's
batch. You don't lose work when you upload a new file.

## Notes

To add a reviewer note:

1. From the **Payment Summary** tab, click **View Invoices** on the entity.
2. The invoice card is expanded by default. Type into the **Reviewer Notes**
   box.
3. Click **Save Note**. A green ✓ Saved confirmation appears briefly.

For invoices on the **>$100K** tab, type directly into the inline note field
and tab/click out — it auto-saves.

Notes survive page refreshes and new spreadsheet uploads.

## Attachments

The dashboard supports two kinds of attachments:

**SharePoint auto-links** — if a bill # contains a `P-#####` and your team
has registered the document in the dashboard's mapping, you'll see a
**📎 SF Approved Doc — P-XXXXX** button that links straight to the file on
SharePoint. If the bill has a `P-#####` but isn't mapped, you'll see a hint
to check the SF Approved folder.

**Manual attachments** — you can attach any supporting file (receipts,
emails, screenshots) directly to an invoice:

1. In the invoice drilldown, click **+ Attach File** and pick one or more
   files.
2. The chips that appear are clickable — they download the file back.
3. Click the **×** on a chip to delete the attachment.

Manual attachments are stored on the server and are tied to the invoice by
entity + bill #, so they persist across uploads.

## Browsing previous dashboards

Every spreadsheet you upload is preserved in the database. To go back in time
and review a prior day's batch:

1. In the top right of the navigation bar (next to **⬇ Download Dashboard**),
   open the **upload history** dropdown.
2. Pick any prior upload — it's labeled with the original filename and the
   upload timestamp. The most recent upload is tagged **(latest)**.
3. The Summary, Hold List, >$100K, and Spot Check tabs all switch to that
   snapshot. A small orange **⏱ Viewing historical snapshot** indicator
   appears on the Summary tab so you don't lose track.
4. Pick the latest entry (or upload a new file) to return to the current view.

Reviewer notes carry across all snapshots — if you added a note to invoice
`B-001` last week, you'll still see it next to the same `B-001` whether
you're looking at last week's batch or today's. Same for manual attachments.

This historical archive is the foundation for future analytics features
(trend reports, year-over-year comparisons, etc.).

## Downloading a snapshot

The **⬇ Download Dashboard** button (top right) generates a self-contained
HTML snapshot of the current state — entity summary, every invoice grouped by
entity, the hold list, with reviewer notes and attachment names included.
Useful for emailing or attaching to a daily review record.

## Troubleshooting

| Symptom                                       | Likely cause / fix                                                                 |
| --------------------------------------------- | ---------------------------------------------------------------------------------- |
| "No data uploaded yet" banner                 | Upload a spreadsheet via the **Upload New Data** tab.                              |
| Upload fails with "Cannot find Vendor or Amount columns" | The header row in the AP sheet doesn't match expected names. Check column titles. |
| Upload fails with "AP sheet appears empty"    | The workbook has fewer than 2 rows or no recognizable AP/Dashboard sheet.          |
| An invoice that should be on hold isn't       | The hold list vendor name doesn't match the invoice vendor closely enough. The matcher uses a 12-character prefix in either direction. |
| Note didn't save                              | A toast will pop up with the error. Network issue is the most common cause; try again. |
| Attachment chip download returns 404          | The file was removed from disk out-of-band. Delete the broken chip and re-attach.  |

For anything else, check the browser console and the `web` container logs:

```bash
docker compose logs -f web
```
