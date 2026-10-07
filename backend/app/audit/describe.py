"""What a successful change looks like in the activity log: a category, one readable sentence
and the details behind it. Pure: takes the request (method, path, query, JSON body) and the
response headers; never reads files or the database.

Secrets (passcodes, passwords, tokens) never reach the log. "{employee}" in a summary is
filled in with the employee's name by service.record.
"""
import json
import re
from decimal import Decimal, InvalidOperation

from ..designers.models import STATUSES
from ..production.models import STAGES

SECRET_KEYS = ("passcode", "password", "token", "secret")
TEXT_MAX = 200
LIST_MAX = 40
DETAILS_MAX = 8000

SERIES_NAMES = {"quotation": "Quotation", "non_gst": "Invoice", "gst": "GST invoice"}
MODES = {"upi": "UPI", "cash": "cash", "bank_transfer": "bank transfer", "cheque": "cheque"}

# Mutating routes that are not changes to the shop's records.
NOT_LOGGED = ("/api/calculate", "/api/login", "/api/logout")


def redact(value, depth: int = 0):
    """A copy safe to store: secrets masked, long text and lists cut short."""
    if depth > 6:
        return "…"
    if isinstance(value, dict):
        return {
            k: ("•••" if any(s in str(k).lower() for s in SECRET_KEYS) else redact(v, depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, list):
        items = [redact(v, depth + 1) for v in value[:LIST_MAX]]
        return items + ([f"… {len(value) - LIST_MAX} more"] if len(value) > LIST_MAX else [])
    if isinstance(value, str) and len(value) > TEXT_MAX:
        return value[:TEXT_MAX] + "…"
    return value


def _money(value) -> str:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    text = f"{d:,.2f}"
    return "₹" + (text[:-3] if text.endswith(".00") else text)


def _changes(body: dict, labels: dict[str, str] | None = None) -> str:
    """'status → Final design, vendor → Sharma Printers' from a PATCH body."""
    labels = labels or {}
    parts = []
    for key, value in body.items():
        if any(s in key.lower() for s in SECRET_KEYS):
            continue
        name = labels.get(key, key.replace("_", " "))
        if isinstance(value, bool):
            shown = "yes" if value else "no"
        elif value in (None, ""):
            shown = "(cleared)"
        else:
            shown = str(value)
        parts.append(f"{name} → {shown}")
    return ", ".join(parts) or "no fields"


def _series(query: dict, body: dict | None = None) -> str:
    series = (body or {}).get("series") or query.get("series") or "non_gst"
    return SERIES_NAMES.get(series, series)


def _invoice_created(body: dict, headers: dict) -> tuple[str, dict]:
    series = headers.get("x-document-series") or ("quotation" if body.get("document_type") == "quotation" else body.get("bill_type") or "non_gst")
    number = headers.get("x-bill-no") or body.get("bill_no") or "?"
    gst = body.get("gst") or {}
    customer = ((gst.get("buyer") or {}).get("name") if series == "gst" else None) or (body.get("customer") or {}).get("business_name") or "no name"
    lines = [l for l in body.get("lines") or [] if isinstance(l, dict)]
    total = Decimal(0)
    for l in lines:
        try:
            total += Decimal(str(l.get("quantity"))) * Decimal(str(l.get("unit_price")))
        except (InvalidOperation, ValueError, TypeError):
            pass
    doc = SERIES_NAMES.get(series, series)
    summary = f"Created {doc} #{number} for {customer}: {len(lines)} line{'' if len(lines) == 1 else 's'}, {_money(total)} before tax"
    if series != "quotation" and body.get("print_mode"):
        summary += f" ({body['print_mode']})"
    details = {
        "document": doc,
        "number": number,
        "customer": customer,
        "print_mode": body.get("print_mode"),
        "gst_slab": body.get("gst_slab"),
        "items_total_before_tax": f"{total:.2f}",
        "saving_amount": body.get("saving_amount"),
        "advance_pct": body.get("advance_pct"),
        "lines": [
            {
                "title": l.get("title"),
                "kind": l.get("source"),
                "quantity": l.get("quantity"),
                "unit": l.get("unit_label"),
                "unit_price": l.get("unit_price"),
                **({"catalogue_price": l["catalogue_unit_price"]} if l.get("catalogue_unit_price") not in (None, l.get("unit_price")) else {}),
                **({"customisations": [c.get("value") for c in l["customisations"] if isinstance(c, dict)]} if l.get("customisations") else {}),
            }
            for l in lines
        ],
        "payments": body.get("payments") or [],
    }
    return summary, details


ROUTES: list[tuple[str, str, str]] = [
    # (method, path regex, handler key)
    ("POST", r"/api/invoices", "invoice_create"),
    ("POST", r"/api/invoices/(?P<no>\d+)/payments", "payment"),
    ("DELETE", r"/api/invoices/(?P<no>\d+)", "invoice_delete"),
    ("POST", r"/api/staff/login", "staff_login"),
    ("POST", r"/api/team/admin/login", "admin_login"),
    ("POST", r"/api/designers", "designer_add"),
    ("PATCH", r"/api/designers/(?P<id>\d+)", "designer_edit"),
    ("PATCH", r"/api/jobs/(?P<id>\d+)", "design_job"),
    ("PATCH", r"/api/jobs/(?P<id>\d+)/products/(?P<line>\d+)", "design_item"),
    ("POST", r"/api/production/employees", "production_employee"),
    ("POST", r"/api/production/jobs", "production_add"),
    ("PATCH", r"/api/production/jobs/(?P<id>\d+)", "production_job"),
    ("PATCH", r"/api/production/jobs/(?P<id>\d+)/products/(?P<line>\d+)/stages/(?P<stage>\d+)", "production_stage"),
    ("DELETE", r"/api/production/jobs/(?P<id>\d+)", "production_remove"),
    ("POST", r"/api/team/employees", "employee_add"),
    ("PATCH", r"/api/team/employees/(?P<emp>\d+)", "employee_edit"),
    ("DELETE", r"/api/team/employees/(?P<emp>\d+)", "employee_remove"),
    ("POST", r"/api/team/employees/(?P<emp>\d+)/restore", "employee_restore"),
    ("POST", r"/api/team/attendance/check-in", "check_in"),
    ("POST", r"/api/team/attendance/check-out", "check_out"),
    ("PUT", r"/api/team/attendance/(?P<emp>\d+)/(?P<day>[\d-]+)", "attendance_set"),
    ("DELETE", r"/api/team/attendance/(?P<emp>\d+)/(?P<day>[\d-]+)", "attendance_delete"),
]


def logged(method: str, path: str) -> bool:
    return method in ("POST", "PUT", "PATCH", "DELETE") and path.startswith("/api/") and path not in NOT_LOGGED \
        and not path.startswith("/api/admin/")


def describe(method: str, path: str, query: dict, body, headers: dict) -> tuple[str, str, dict]:
    """(category, summary, details) for a change that succeeded."""
    body = body if isinstance(body, dict) else {}
    headers = {k.lower(): v for k, v in headers.items()}
    for m, pattern, key in ROUTES:
        match = re.fullmatch(pattern, path)
        if m == method and match:
            p = match.groupdict()
            break
    else:
        return "other", f"{method} {path}", {"body": redact(body), "query": redact(query)}

    if key == "invoice_create":
        summary, details = _invoice_created(body, headers)
        return "invoices", summary, details
    if key == "payment":
        doc = _series(query)
        mode = MODES.get(body.get("mode", "upi"), body.get("mode"))
        summary = f"Recorded a payment of {_money(body.get('amount'))} ({mode}) on {doc} #{p['no']}"
        if body.get("date"):
            summary += f", dated {body['date']}"
        return "invoices", summary, redact(body)
    if key == "invoice_delete":
        return "invoices", f"Deleted {_series(query)} #{p['no']}", {"number": p["no"], "series": query.get("series", "non_gst")}
    if key == "staff_login":
        return "access", "Signed in with the staff passcode", {}
    if key == "admin_login":
        return "access", "Unlocked admin with the admin passcode", {}
    if key == "designer_add":
        return "design", f"Added designer {body.get('name', '')}", redact(body)
    if key == "designer_edit":
        return "design", f"Edited designer #{p['id']}: {_changes(body)}", redact(body)
    if key in ("design_job", "design_item"):
        shown = {**body}
        if isinstance(body.get("status"), int):
            shown["status"] = STATUSES.get(body["status"], body["status"])
        where = f"design job #{p['id']}" + (f", product {int(p['line']) + 1}" if key == "design_item" else "")
        return "design", f"Updated {where}: {_changes(shown)}", redact(body)
    if key == "production_employee":
        return "production", f"Added production employee {body.get('name', '')}", redact(body)
    if key == "production_add":
        doc = SERIES_NAMES.get(body.get("series", "non_gst"), "Invoice")
        return "production", f"Put {doc} #{body.get('bill_no', '?')} into production", redact(body)
    if key == "production_job":
        return "production", f"Updated production job #{p['id']}: {_changes(body, {'employee_id': 'employee'})}", redact(body)
    if key == "production_stage":
        stage = STAGES.get(int(p["stage"]), "")
        summary = f"Production job #{p['id']}, product {int(p['line']) + 1}, stage {p['stage']} {stage}: {_changes(body)}"
        return "production", summary, redact(body)
    if key == "production_remove":
        return "production", f"Removed production job #{p['id']}", {}
    if key == "employee_add":
        return "employees", f"Added employee {body.get('name', '')} ({body.get('role', '')})", redact(body)
    if key == "employee_edit":
        return "employees", "Edited {employee}: " + _changes(body), {**redact(body), "employee_id": int(p["emp"])}
    if key == "employee_remove":
        return "employees", "Removed {employee} from the team", {"employee_id": int(p["emp"])}
    if key == "employee_restore":
        return "employees", "Restored {employee} to the team", {"employee_id": int(p["emp"])}
    if key == "check_in":
        return "attendance", "Checked in {employee}", {"employee_id": body.get("employee_id")}
    if key == "check_out":
        return "attendance", "Checked out {employee}", {"employee_id": body.get("employee_id")}
    if key == "attendance_set":
        times = f"in {body.get('check_in', '?')}, out {body.get('check_out') or '—'}"
        note = f" (note: {body['note']})" if body.get("note") else ""
        return "attendance", f"Set {{employee}}'s attendance on {p['day']}: {times}{note}", {**redact(body), "employee_id": int(p["emp"]), "date": p["day"]}
    if key == "attendance_delete":
        return "attendance", f"Deleted {{employee}}'s attendance on {p['day']}", {"employee_id": int(p["emp"]), "date": p["day"]}
    return "other", f"{method} {path}", redact(body)


def details_json(details: dict) -> str:
    text = json.dumps(details, ensure_ascii=False, default=str)
    return text if len(text) <= DETAILS_MAX else text[:DETAILS_MAX] + "…"
