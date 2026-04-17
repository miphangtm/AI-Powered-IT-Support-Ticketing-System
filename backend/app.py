"""
ClearDesk — Flask API Server
----------------------------
Exposes a REST API for the IT support ticketing system.

Responsibilities of this module:
  - HTTP routing and request/response shaping
  - Input validation at the API boundary
  - Coordinating classifier.py (AI) and db.py (persistence)

It deliberately owns no AI logic and no SQL — those concerns live in their
own modules so each can be tested and changed independently.
"""

import logging
import os
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

import db
from classifier import (
    VALID_CATEGORIES,
    VALID_URGENCIES,
    ClassificationError,
    classify_ticket,
    make_client,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Allow all origins in dev; tighten to a specific origin in production,
# e.g. CORS(app, origins=["https://cleardesk.example.com"])
CORS(app)

# Build the shared Gemini client once at startup — thread-safe, reused per request.
# make_client() is imported from classifier.py so AI configuration stays
# co-located with the classification logic, not scattered across modules.
_api_key = os.environ.get("GEMINI_API_KEY")
if not _api_key:
    raise RuntimeError(
        "GEMINI_API_KEY is not set. "
        "Copy backend/.env.example to backend/.env and add your key."
    )
_gemini_client = make_client(_api_key)

# Status values live here (not in classifier.py) because they model workflow
# state, not AI output — the classifier never touches this set.
VALID_STATUSES: frozenset[str] = frozenset({"Open", "In Progress", "Resolved"})

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with a Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_ticket_id() -> str:
    """Generate a short, uppercase ticket ID (8 hex characters)."""
    return str(uuid.uuid4())[:8].upper()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/api/tickets", methods=["GET"])
def list_tickets():
    """
    Return tickets ordered newest-first.

    Optional query parameters (all case-sensitive, must match DB values exactly):
      ?category=Network|Hardware|Software|Access|Other
      ?urgency=Low|Medium|High
      ?status=Open|In+Progress|Resolved

    Returns 400 if an unrecognised filter value is supplied so clients get
    immediate feedback on a typo rather than a silently empty result set.
    Multiple filters are ANDed together.

    Example: GET /api/tickets?status=Open&urgency=High
    """
    # Read raw query param values — args.get() returns None when absent.
    raw_category = request.args.get("category")
    raw_urgency  = request.args.get("urgency")
    raw_status   = request.args.get("status")

    # Validate each supplied filter against its allowed set.
    # None means "not supplied" and is passed through to db.list_tickets()
    # unchanged so no WHERE condition is added for that column.
    if raw_category is not None and raw_category not in VALID_CATEGORIES:
        return jsonify({
            "error": f"Invalid category {raw_category!r}. "
                     f"Must be one of: {sorted(VALID_CATEGORIES)}",
        }), 400

    if raw_urgency is not None and raw_urgency not in VALID_URGENCIES:
        return jsonify({
            "error": f"Invalid urgency {raw_urgency!r}. "
                     f"Must be one of: {sorted(VALID_URGENCIES)}",
        }), 400

    if raw_status is not None and raw_status not in VALID_STATUSES:
        return jsonify({
            "error": f"Invalid status {raw_status!r}. "
                     f"Must be one of: {sorted(VALID_STATUSES)}",
        }), 400

    tickets = db.list_tickets(
        category=raw_category,
        urgency=raw_urgency,
        status=raw_status,
    )
    return jsonify(tickets)


@app.route("/api/tickets", methods=["POST"])
def create_ticket():
    """
    Create a new ticket.

    Required JSON body fields: title, description
    Optional: submitter (defaults to 'Anonymous')

    The ticket is always created even if classification fails — the AI
    result is best-effort.  A failed classification logs a warning and
    falls back to safe defaults rather than returning a 5xx to the user.
    """
    data = request.get_json(force=True) or {}

    title       = data.get("title", "").strip()
    description = data.get("description", "").strip()
    submitter   = data.get("submitter", "").strip() or "Anonymous"

    if not title or not description:
        return jsonify({"error": "title and description are required"}), 400

    # Classify with Claude.  Runs synchronously — for high traffic, move to a
    # task queue (e.g. Celery) and let the client poll for the result.
    try:
        result = classify_ticket(title, description, client=_gemini_client)
        category             = result["category"]
        urgency              = result["urgency"]
        suggested_resolution = result["suggested_resolution"]
    except ClassificationError as exc:
        # Log the full error (including raw_response if available) for debugging,
        # but don't surface AI internals to the client.
        logger.warning(
            "Classification failed for ticket '%s': %s | raw=%r",
            title, exc, exc.raw_response,
        )
        category             = "Other"
        urgency              = "Medium"
        suggested_resolution = ""

    now = utc_now_iso()

    ticket = db.create_ticket(
        ticket_id            = make_ticket_id(),
        title                = title,
        description          = description,
        submitter            = submitter,
        category             = category,
        urgency              = urgency,
        suggested_resolution = suggested_resolution,
        created_at           = now,
        updated_at           = now,
    )

    return jsonify(ticket), 201


@app.route("/api/tickets/<ticket_id>", methods=["GET"])
def get_ticket(ticket_id: str):
    """Return a single ticket by ID."""
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404
    return jsonify(ticket)


@app.route("/api/tickets/<ticket_id>", methods=["PATCH"])
def update_ticket(ticket_id: str):
    """
    Partially update a ticket.

    Accepted fields and their allowed values:
      status   — Open | In Progress | Resolved
      urgency  — Low | Medium | High
      category — Network | Hardware | Software | Access | Other

    Fields with unknown or out-of-range values are silently ignored so the
    API stays lenient for future frontend additions.
    """
    data = request.get_json(force=True) or {}

    # Map each updatable field to its set of valid values.
    # VALID_CATEGORIES and VALID_URGENCIES are imported from classifier.py
    # so there's a single source of truth for what values are allowed.
    field_validators = {
        "status":   VALID_STATUSES,
        "urgency":  VALID_URGENCIES,
        "category": VALID_CATEGORIES,
    }

    # Build a dict of only validated changes — never pass unvalidated client
    # data directly to the database layer.
    updates = {
        field: data[field]
        for field, allowed in field_validators.items()
        if data.get(field) in allowed
    }

    # Always stamp the update time so the client can see the record was touched,
    # even when the only change was e.g. an idempotent status re-set.
    updates["updated_at"] = utc_now_iso()

    ticket = db.update_ticket(ticket_id, updates)
    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404

    return jsonify(ticket)


# ---------------------------------------------------------------------------
# Global error handlers
# ---------------------------------------------------------------------------
# Flask's default error responses are HTML, which breaks JSON-only clients.
# These handlers ensure every error — including unhandled exceptions — comes
# back as a consistent JSON envelope.

@app.errorhandler(400)
def bad_request(exc):
    """Return a JSON 400 for malformed requests Flask catches before our code runs."""
    return jsonify({"error": str(exc.description)}), 400


@app.errorhandler(404)
def not_found(exc):
    """Return a JSON 404 instead of Flask's default HTML page."""
    return jsonify({"error": "The requested resource was not found."}), 404


@app.errorhandler(405)
def method_not_allowed(exc):
    """Return a JSON 405 when the HTTP method is not supported on a route."""
    return jsonify({"error": "Method not allowed."}), 405


@app.errorhandler(500)
def internal_error(exc):
    """
    Catch-all for unhandled exceptions.

    The exception is already logged by Flask's default exception handler so
    we only need to shape the client-facing response here.  Never expose
    internal details (stack traces, DB errors) to the client.
    """
    logger.exception("Unhandled exception: %s", exc)
    return jsonify({"error": "An unexpected server error occurred."}), 500


# ---------------------------------------------------------------------------
# Application startup
# ---------------------------------------------------------------------------

# Initialise the database schema before the first request is handled.
# Idempotent — safe to call on every restart.
with app.app_context():
    db.init_db()


if __name__ == "__main__":
    # debug=True enables auto-reload and detailed tracebacks.
    # Never use in production.
    app.run(debug=True, port=5000)
