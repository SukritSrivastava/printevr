/**
 * Printevr Quote Desk -> Google Sheets sync.
 *
 * Paste this whole file into the Google Sheet (Extensions -> Apps Script), set the Script
 * Properties APP_URL and EXPORT_SECRET, then run setup() once. Step-by-step guide:
 * docs/google-sheets-sync.md in the app's repository.
 *
 * Every 15 minutes syncAll() reads the app's read-only export API (GET /api/export/<section>)
 * and writes each section to its own tab:
 *   - Most tabs are replaced as a whole, but only after every page of that section arrived.
 *     If anything fails, that tab is left as it was and the error shows on "Sync status".
 *   - Logs only gets new entries appended (?since= the newest entry already synced).
 * The column keys below must match backend/app/export/sections.py COLUMNS (a test checks).
 */

const SECTIONS = [
  {
    key: 'invoices', tab: 'Invoices', columns: [
      ['type', 'Type'], ['bill_no', 'Bill No', 'int'], ['invoice_date', 'Invoice Date', 'date'],
      ['business_name', 'Business Name'], ['gst_slab', 'GST Slab'], ['line_count', 'Lines', 'int'],
      ['total', 'Total', 'amount'], ['gst_amount', 'GST Amount', 'amount'], ['saving', 'Saving', 'amount'],
      ['payable', 'Payable', 'amount'], ['advance_pct', 'Advance %', 'num'], ['received', 'Received', 'amount'],
      ['pending', 'Pending', 'amount'], ['status', 'Status'], ['payment_count', 'Payments', 'int'],
      ['last_payment_date', 'Last Payment Date', 'date'], ['payment_modes', 'Payment Modes'],
      ['created_at', 'Created', 'datetime'], ['updated_at', 'Updated', 'datetime'],
    ],
  },
  {
    key: 'invoice-items', tab: 'Invoice Items', columns: [
      ['type', 'Type'], ['bill_no', 'Bill No', 'int'], ['invoice_date', 'Invoice Date', 'date'],
      ['business_name', 'Business Name'], ['line_no', 'Line #', 'int'], ['kind', 'Kind'],
      ['parent_line_no', 'Parent Line #', 'int'], ['product', 'Product'], ['specs', 'Specs'],
      ['customisations', 'Free Customisations'], ['quantity', 'Qty', 'num'], ['unit', 'Unit'],
      ['unit_price', 'Unit Price', 'amount'], ['catalogue_unit_price', 'Catalogue Unit Price', 'amount'],
      ['line_amount', 'Line Amount', 'amount'], ['price_edited', 'Price Edited', 'bool'], ['hsn_code', 'HSN'],
    ],
  },
  {
    key: 'designer-jobs', tab: 'Designer Jobs', columns: [
      ['type', 'Type'], ['bill_no', 'Invoice #', 'int'], ['customer', 'Customer'], ['line_no', 'Line #', 'int'],
      ['product', 'Product'], ['quantity', 'Qty', 'num'], ['unit', 'Unit'], ['size', 'Size'],
      ['addons', 'Add-ons'], ['designer', 'Designer'], ['status_no', 'Status #', 'int'], ['status', 'Status'],
      ['pending', 'Pending', 'bool'], ['vendor', 'Vendor'], ['assigned_at', 'Assigned', 'datetime'],
      ['updated_at', 'Updated', 'datetime'],
    ],
  },
  {
    key: 'production', tab: 'Production', columns: [
      ['type', 'Type'], ['bill_no', 'Invoice #', 'int'], ['customer', 'Customer'], ['line_no', 'Line #', 'int'],
      ['product', 'Product'], ['quantity', 'Qty', 'num'], ['unit', 'Unit'], ['employee', 'Assigned Employee'],
      ['stage_no', 'Current Stage #', 'int'], ['stage', 'Current Stage'], ['stages_done', 'Stages Done (of 10)', 'int'],
      ['complete', 'Complete', 'bool'], ['vendor', 'Vendor (current stage)'], ['created_at', 'Created', 'datetime'],
      ['updated_at', 'Updated', 'datetime'],
    ],
  },
  {
    key: 'attendance', tab: 'Attendance', columns: [
      ['work_date', 'Date', 'date'], ['employee_id', 'Employee ID', 'int'], ['employee', 'Employee'],
      ['role', 'Role'], ['check_in', 'Check In', 'datetime'], ['check_out', 'Check Out', 'datetime'],
      ['hours', 'Hours', 'num'], ['still_in', 'Still In', 'bool'], ['note', 'Note'],
      ['edited_by_admin', 'Edited by Admin', 'bool'], ['updated_at', 'Updated', 'datetime'],
    ],
  },
  {
    key: 'employees', tab: 'Employees', columns: [
      ['id', 'ID', 'int'], ['name', 'Name'], ['role', 'Role'], ['joined_on', 'Joined On', 'date'],
      ['active', 'Active', 'bool'], ['created_at', 'Created', 'datetime'], ['updated_at', 'Updated', 'datetime'],
    ],
  },
  {
    key: 'logs', tab: 'Logs', append: true, columns: [
      ['id', 'ID', 'int'], ['at', 'Time', 'datetime'], ['category', 'Category'], ['summary', 'Summary'],
      ['actor_role', 'Who'], ['actor_name', 'Name'], ['method', 'Method'], ['path', 'Path'],
      ['status', 'Status', 'int'],
    ],
  },
];

const STATUS_TAB = 'Sync status';
const TIME_ZONE = 'Asia/Kolkata';
const PAGE_SIZE = 500;
const MAX_PAGES = 400;
// Apps Script stops a run after 6 minutes; stop starting new work well before that.
const TIME_BUDGET_MS = 4.5 * 60 * 1000;
// Logs are fetched from a little before the newest synced entry and de-duplicated by ID, so an
// entry saved a moment late isn't missed.
const LOGS_OVERLAP_MS = 2 * 60 * 1000;
const FORMATS = {
  amount: '₹#,##0.00',
  date: 'dd MMM yyyy',
  datetime: 'dd MMM yyyy, hh:mm a',
  int: '0',
};

function onOpen() {
  SpreadsheetApp.getUi().createMenu('Printevr').addItem('Sync now', 'syncAll').addToUi();
}

/** Run once: makes the 15-minute trigger (only if it isn't there yet), then syncs. */
function setup() {
  const exists = ScriptApp.getProjectTriggers().some(function (t) {
    return t.getHandlerFunction() === 'syncAll';
  });
  if (!exists) {
    ScriptApp.newTrigger('syncAll').timeBased().everyMinutes(15).create();
  }
  syncAll();
}

/** Empties the Logs tab and fetches every log entry again on the next sync. */
function resetLogs() {
  PropertiesService.getScriptProperties().deleteProperty('LOGS_SINCE');
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Logs');
  if (sheet) sheet.clear();
}

function syncAll() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return; // another sync is still running
  try {
    const started = Date.now();
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    if (ss.getSpreadsheetTimeZone() !== TIME_ZONE) ss.setSpreadsheetTimeZone(TIME_ZONE);
    const props = PropertiesService.getScriptProperties();
    const status = readStatus_(props);
    const config = readConfig_(props);
    SECTIONS.forEach(function (section) {
      const entry = status[section.key] || {};
      entry.attempt = new Date().toISOString();
      try {
        if (config.error) throw new Error(config.error);
        if (Date.now() - started > TIME_BUDGET_MS) throw new Error('Out of time this run; will retry next run');
        entry.rows = section.append
          ? syncAppend_(ss, props, config, section, started)
          : syncReplace_(ss, config, section, started);
        entry.ok = entry.attempt;
        entry.error = '';
      } catch (e) {
        entry.error = String(e && e.message ? e.message : e);
      }
      status[section.key] = entry;
    });
    props.setProperty('SYNC_STATUS', JSON.stringify(status));
    writeStatus_(ss, status);
  } finally {
    lock.releaseLock();
  }
}

function readConfig_(props) {
  const url = (props.getProperty('APP_URL') || '').trim().replace(/\/+$/, '');
  const secret = (props.getProperty('EXPORT_SECRET') || '').trim();
  if (!url || !secret) return { error: 'Set APP_URL and EXPORT_SECRET in Project Settings -> Script Properties' };
  if (!/^https:\/\//.test(url)) return { error: 'APP_URL must start with https://' };
  return { url: url, secret: secret };
}

/** Every page of a section, or an error. Nothing is written to the sheet here. */
function fetchAll_(config, section, query, started) {
  const rows = [];
  let page = 1;
  while (page) {
    if (page > MAX_PAGES) throw new Error('Too many pages');
    if (Date.now() - started > TIME_BUDGET_MS) throw new Error('Out of time this run; will retry next run');
    let url = config.url + '/api/export/' + section.key + '?page=' + page + '&pageSize=' + PAGE_SIZE;
    if (query) url += '&' + query;
    const response = UrlFetchApp.fetch(url, {
      method: 'get',
      headers: { Authorization: 'Bearer ' + config.secret },
      muteHttpExceptions: true,
      followRedirects: false,
    });
    const code = response.getResponseCode();
    let body = null;
    try {
      body = JSON.parse(response.getContentText());
    } catch (e) {
      body = null;
    }
    if (code !== 200 || !body || !Array.isArray(body.rows)) {
      const reason = body && body.error ? body.error.code + ': ' + body.error.message : 'unexpected response';
      throw new Error('HTTP ' + code + ' (' + reason + ')');
    }
    Array.prototype.push.apply(rows, body.rows);
    page = body.nextPage || null;
  }
  return rows;
}

function syncReplace_(ss, config, section, started) {
  const rows = fetchAll_(config, section, '', started).reverse(); // newest first
  const sheet = sheetFor_(ss, section.tab);
  sheet.clear();
  writeHeader_(sheet, section);
  if (rows.length) writeRows_(sheet, section, rows, 2);
  return rows.length;
}

function syncAppend_(ss, props, config, section, started) {
  const since = props.getProperty('LOGS_SINCE');
  const query = since ? 'since=' + encodeURIComponent(new Date(Date.parse(since) - LOGS_OVERLAP_MS).toISOString()) : '';
  const fetched = fetchAll_(config, section, query, started);
  const sheet = sheetFor_(ss, section.tab);
  if (sheet.getLastRow() === 0) writeHeader_(sheet, section);
  const have = {};
  if (sheet.getLastRow() > 1) {
    sheet.getRange(2, 1, sheet.getLastRow() - 1, 1).getValues().forEach(function (r) {
      have[String(r[0])] = true;
    });
  }
  const fresh = fetched.filter(function (row) {
    return !have[String(row.id)];
  });
  if (fresh.length) writeRows_(sheet, section, fresh, sheet.getLastRow() + 1);
  let newest = since ? Date.parse(since) : 0;
  fetched.forEach(function (row) {
    const at = Date.parse(trimFraction_(row.at));
    if (at > newest) newest = at;
  });
  if (newest) props.setProperty('LOGS_SINCE', new Date(newest).toISOString());
  return sheet.getLastRow() - 1;
}

function sheetFor_(ss, name) {
  return ss.getSheetByName(name) || ss.insertSheet(name);
}

function writeHeader_(sheet, section) {
  const labels = section.columns.map(function (c) {
    return c[1];
  });
  sheet.getRange(1, 1, 1, labels.length).setValues([labels]).setFontWeight('bold');
  sheet.setFrozenRows(1);
}

function writeRows_(sheet, section, rows, firstRow) {
  const values = rows.map(function (row) {
    return section.columns.map(function (c) {
      return cell_(row[c[0]], c[2]);
    });
  });
  sheet.getRange(firstRow, 1, values.length, section.columns.length).setValues(values);
  section.columns.forEach(function (c, i) {
    if (FORMATS[c[2]]) sheet.getRange(firstRow, i + 1, values.length, 1).setNumberFormat(FORMATS[c[2]]);
  });
}

function cell_(value, type) {
  if (value === null || value === undefined || value === '') return '';
  if (type === 'bool') return value ? 'Yes' : 'No';
  if (type === 'date') return new Date(value + 'T00:00:00+05:30');
  if (type === 'datetime') return new Date(trimFraction_(value));
  return value;
}

/** "...T03:30:00.123456+00:00" -> "...T03:30:00.123+00:00" (JavaScript reads milliseconds only). */
function trimFraction_(iso) {
  return String(iso).replace(/(\.\d{3})\d+/, '$1');
}

function readStatus_(props) {
  try {
    return JSON.parse(props.getProperty('SYNC_STATUS') || '{}');
  } catch (e) {
    return {};
  }
}

function writeStatus_(ss, status) {
  const sheet = sheetFor_(ss, STATUS_TAB);
  sheet.clear();
  const values = [['Tab', 'Last successful sync', 'Rows', 'Last attempt', 'Error']];
  SECTIONS.forEach(function (section) {
    const s = status[section.key] || {};
    values.push([
      section.tab,
      s.ok ? new Date(s.ok) : '',
      s.rows === undefined ? '' : s.rows,
      s.attempt ? new Date(s.attempt) : '',
      s.error || '',
    ]);
  });
  sheet.getRange(1, 1, values.length, values[0].length).setValues(values);
  sheet.getRange(1, 1, 1, values[0].length).setFontWeight('bold');
  sheet.setFrozenRows(1);
  sheet.getRange(2, 2, values.length - 1, 1).setNumberFormat(FORMATS.datetime);
  sheet.getRange(2, 4, values.length - 1, 1).setNumberFormat(FORMATS.datetime);
}
