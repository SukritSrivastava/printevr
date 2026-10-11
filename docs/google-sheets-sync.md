# Copying Printevr data into a Google Sheet

Every 15 minutes, a Google Sheet copies these from the Printevr Quote Desk, each into its own tab:

| Tab | One row per |
|---|---|
| Invoices | invoice (Non-GST and GST; quotations aren't included) |
| Invoice Items | line on an invoice (products, add-ons, customisations) |
| Designer Jobs | product being designed |
| Production | product in production |
| Attendance | employee's working day |
| Employees | employee |
| Logs | change made in the app (new entries are added at the bottom) |
| Sync status | tab: when it last synced, how many rows, and any error |

The sheet only **reads** from the app. It can't change anything in the app, and the website looks
and works exactly as before.

Left out on purpose: customer phone numbers, addresses and contact names, GSTINs, employee phone
numbers and emails, and the IP address, device and details of log entries. Passwords, passcodes
and keys are never sent.

Setup takes about 15 minutes. You need:
- access to the project on **Vercel** (vercel.com)
- the **Google account that receives the invoice emails**

---

## Step 1: Make a secret key

The sheet proves it's allowed to read the data with a long secret key that only Vercel and the
sheet know. Treat it like a password.

1. On a Windows computer, open **PowerShell** (Start menu → type `PowerShell` → open it).
2. Paste this line and press Enter:

   ```
   -join ((1..64) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })
   ```

   On a Mac, open **Terminal** and run `openssl rand -hex 32` instead.
3. You get 64 letters and digits, like `3f9a…c21e`. Copy them into a safe note for the next steps.
   Never put the key in an email, a chat or the sheet itself.

The key must be at least 32 characters, or the app won't turn the export on.

## Step 2: Add the key in Vercel and redeploy

1. Go to **vercel.com**, sign in, and open the Printevr project.
2. Click **Settings** → **Environment Variables**.
3. Add a variable:
   - **Key:** `EXPORT_SECRET`
   - **Value:** the key from Step 1
   - **Environments:** tick **Production** (Preview isn't needed)
4. Click **Save**.
5. The new variable takes effect only after a redeploy: click **Deployments**, open the menu
   (**⋯**) on the top (current production) deployment, choose **Redeploy**, and confirm.
6. Wait until it says **Ready**.
7. Note the website address you use every day, e.g. `https://printevr-quote-desk.vercel.app`.
   That's your **APP_URL**.

## Step 3: Create the sheet and paste the script

1. Open a browser window signed in **only to the invoice email Google account**. A private or
   incognito window works well; otherwise make sure the account icon (top right) shows that account.
2. Go to **sheets.google.com** → **Blank spreadsheet**. Name it, e.g. *Printevr data*.
3. In the sheet, click **Extensions** → **Apps Script**. A new tab opens with a file called `Code.gs`.
4. Delete everything in `Code.gs`.
5. Open the file `scripts/google-sheets-sync.gs` from the Printevr repository, copy **all** of it,
   and paste it into `Code.gs`.
6. Click the **Save** icon (💾). Name the project *Printevr sync* if asked.

## Step 4: Tell the script where the app is and what the key is

1. In the Apps Script tab, click the **gear icon** (⚙ **Project Settings**) on the left.
2. Scroll down to **Script Properties** → **Add script property**. Add two:

   | Property | Value |
   |---|---|
   | `APP_URL` | your website address from Step 2, starting with `https://`, without anything after `.app` |
   | `EXPORT_SECRET` | the key from Step 1 |

3. Click **Save script properties**.

## Step 5: Run setup() once and allow access

1. Click the **< >** icon (**Editor**) on the left.
2. In the toolbar, pick **setup** from the function drop-down, then click **Run**.
3. Google asks for permission:
   - Click **Review permissions** and choose the invoice email account.
   - You may see **"Google hasn't verified this app."** That's normal for a script you wrote
     yourself: click **Advanced** → **Go to Printevr sync (unsafe)**.
   - Click **Allow**. The script asks to edit this spreadsheet, connect to an external service
     (your app) and run on a schedule.
4. Wait for **Execution completed** at the bottom.
5. Go back to the sheet. The tabs **Invoices, Invoice Items, Designer Jobs, Production,
   Attendance, Employees, Logs** and **Sync status** now exist.
6. Open **Sync status**: every row should have a time under *Last successful sync* and nothing
   under *Error*.

That's it. The sheet now updates itself every 15 minutes, even when it's closed.

---

## Everyday use

- **Sync now:** reload the sheet, then use the menu **Printevr → Sync now**. The first time,
  Google may ask for permission again.
- **Don't edit the data tabs.** Every sync replaces them; only *Logs* keeps old rows. To make
  your own reports, add a **new tab** that uses formulas or a pivot table on these tabs.
- Times are shown in India time (`12 Oct 2026, 09:30 AM`), amounts as `₹32,125.00`. Both are
  real dates and numbers, so sorting, filters and SUM work.
- The newest invoices, jobs and attendance appear at the top. Logs add new entries at the bottom.

## If something goes wrong

Open **Sync status** and read the **Error** column. A tab that failed keeps its previous data.

| Error | What to do |
|---|---|
| `Set APP_URL and EXPORT_SECRET…` | Step 4: a property is missing or misspelt. |
| `HTTP 401 (UNAUTHENTICATED…)` | The key in the sheet and in Vercel differ. Copy it again into both (no spaces), and redeploy after changing Vercel. |
| `HTTP 503 (EXPORT_DISABLED…)` | Vercel doesn't have `EXPORT_SECRET` yet, it's shorter than 32 characters, or you didn't redeploy (Step 2). |
| `HTTP 401` with an HTML page, or `unexpected response` | `APP_URL` is wrong, or Vercel **Deployment Protection** is blocking outside visitors on that address. Use the normal production address you open every day. |
| `HTTP 503 (STORAGE_…)` or `NOT_SET_UP` | The app's database is unavailable or not migrated. Tell whoever runs the server; it fixes itself on the next sync. |
| `Out of time this run` | There was more data than one run could handle; the rest syncs on the next run. |

- **The Logs tab got messed up or deleted:** in Apps Script, run **resetLogs** once, then
  **Printevr → Sync now**. It refetches every log entry.
- **Change the key:** change it in Vercel (and redeploy) **and** in Script Properties.
- **Stop syncing:** in Apps Script, click the **clock icon** (**Triggers**) on the left and delete
  the `syncAll` trigger. To turn the export off completely, delete `EXPORT_SECRET` in Vercel and
  redeploy.

## For developers

- API: `GET /api/export/{invoices|invoice-items|designer-jobs|production|attendance|employees|logs}`
  with `Authorization: Bearer <EXPORT_SECRET>`. Paged with `?page=1&pageSize=500` (max 1000);
  answers `{"rows": [...], "nextPage": n | null}`. `logs` also takes `?since=<ISO time>` (entries
  strictly after it; a time without an offset is read as UTC).
- Code: `backend/app/export/` (routes + row builders), test `backend/tests/test_export.py`. The
  only change outside it is in `backend/app/main.py`: the route is registered there, and
  `/api/export/` skips the site-password check because it checks its own key.
- Columns are `COLUMNS` in `backend/app/export/sections.py` and `SECTIONS` in
  `scripts/google-sheets-sync.gs`; the test keeps them equal. To add a column, change both.
- Read-only: the session is never committed, and on Postgres the transaction is `READ ONLY`.
  GET requests aren't written to the activity log.
