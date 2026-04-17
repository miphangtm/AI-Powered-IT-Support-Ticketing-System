"""
ClearDesk — Database Layer (SQLite)
-------------------------------------
All database access goes through this module.  The rest of the application
never imports sqlite3 directly — keeping persistence concerns isolated here
makes it straightforward to swap SQLite for Postgres later (just rewrite
this file; the routes don't change).

Schema
------
tickets
  id                TEXT        PK  — 8-char uppercase UUID prefix
  title             TEXT        NN
  description       TEXT        NN
  submitter         TEXT        NN  — defaults to 'Anonymous'
  category          TEXT        NN  — Network | Hardware | Software | Access | Other
  urgency           TEXT        NN  — Low | Medium | High
  status            TEXT        NN  — Open | In Progress | Resolved
  suggested_resolution TEXT     NN  — AI-generated; empty string if unavailable
  created_at        TEXT        NN  — UTC ISO-8601 with Z suffix
  updated_at        TEXT        NN  — UTC ISO-8601 with Z suffix
"""

import os
import sqlite3
from contextlib import contextmanager
from typing import Generator

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Allow the database path to be overridden via environment variable so that
# tests can point at an in-memory or temp-file database without touching the
# real data file.
_DB_PATH: str = os.environ.get(
    "DATABASE_PATH",
    os.path.join(os.path.dirname(__file__), "cleardesk.db"),
)

# DDL — kept here so schema and CRUD always stay in sync.
_CREATE_TICKETS_TABLE = """
CREATE TABLE IF NOT EXISTS tickets (
    id                   TEXT PRIMARY KEY,
    title                TEXT NOT NULL,
    description          TEXT NOT NULL,
    submitter            TEXT NOT NULL DEFAULT 'Anonymous',
    category             TEXT NOT NULL DEFAULT 'Other'
                         CHECK(category IN ('Network','Hardware','Software','Access','Other')),
    urgency              TEXT NOT NULL DEFAULT 'Medium'
                         CHECK(urgency IN ('Low','Medium','High')),
    status               TEXT NOT NULL DEFAULT 'Open'
                         CHECK(status IN ('Open','In Progress','Resolved')),
    suggested_resolution TEXT NOT NULL DEFAULT '',
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

@contextmanager
def _get_conn() -> Generator[sqlite3.Connection, None, None]:
    """
    Yield a SQLite connection configured for dict-style row access.

    Using a context manager ensures the connection is always closed even
    when the caller raises an exception.  Each request gets its own
    connection — SQLite handles concurrent reads fine; writes are serialised
    by the WAL journal mode set below.
    """
    conn = sqlite3.connect(_DB_PATH)

    # Return rows as sqlite3.Row objects so callers can access columns by name
    # (e.g. row["title"]) AND by index.  dict(row) converts to a plain dict.
    conn.row_factory = sqlite3.Row

    # Write-Ahead Logging gives better concurrency for multi-threaded Flask
    # (multiple readers don't block a writer and vice-versa).
    conn.execute("PRAGMA journal_mode=WAL;")

    # Enforce foreign-key constraints (none today, but good habit).
    conn.execute("PRAGMA foreign_keys=ON;")

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init_db() -> None:
    """
    Create the database file and apply the schema if it doesn't exist yet.
    Safe to call on every application start — IF NOT EXISTS guards are used
    so existing data is never touched.
    """
    with _get_conn() as conn:
        conn.execute(_CREATE_TICKETS_TABLE)


def create_ticket(
    *,
    ticket_id: str,
    title: str,
    description: str,
    submitter: str,
    category: str,
    urgency: str,
    suggested_resolution: str,
    created_at: str,
    updated_at: str,
) -> dict:
    """
    Insert a new ticket row and return it as a plain dict.

    All field-value validation (e.g. category in allowed set) is done by the
    caller (app.py) before this function is reached; the SQLite CHECK
    constraints act as a last-resort safety net.

    Keyword-only arguments are required to prevent accidental positional
    mismatches when the signature is long.
    """
    sql = """
        INSERT INTO tickets
            (id, title, description, submitter, category, urgency,
             suggested_resolution, created_at, updated_at)
        VALUES
            (:id, :title, :description, :submitter, :category, :urgency,
             :suggested_resolution, :created_at, :updated_at)
    """
    params = {
        "id":                   ticket_id,
        "title":                title,
        "description":          description,
        "submitter":            submitter,
        "category":             category,
        "urgency":              urgency,
        "suggested_resolution": suggested_resolution,
        "created_at":           created_at,
        "updated_at":           updated_at,
    }

    with _get_conn() as conn:
        conn.execute(sql, params)

    # Fetch back rather than returning `params` so the caller always gets data
    # exactly as it was stored (CHECK constraints may normalise values).
    return get_ticket(ticket_id)


def get_ticket(ticket_id: str) -> dict | None:
    """
    Return a single ticket as a plain dict, or None if not found.

    The ticket_id is uppercased here (and in every other function) so callers
    never have to remember to normalise case themselves.
    """
    sql = "SELECT * FROM tickets WHERE id = ?"

    with _get_conn() as conn:
        row = conn.execute(sql, (ticket_id.upper(),)).fetchone()

    return dict(row) if row else None


def list_tickets(
    *,
    category: str | None = None,
    urgency:  str | None = None,
    status:   str | None = None,
) -> list[dict]:
    """
    Return tickets ordered newest-first, with optional equality filters.

    All filter arguments are keyword-only to prevent positional confusion.
    Passing None (the default) for any filter means "don't filter on that column".

    The WHERE clause is built dynamically but always uses positional
    placeholders (?) so there is no SQL injection risk regardless of the
    filter values passed in.

    Args:
        category: Exact category to match, e.g. "Network".
        urgency:  Exact urgency to match, e.g. "High".
        status:   Exact status to match, e.g. "Open".

    Returns:
        List of ticket dicts, newest first.  Empty list if no rows match.
    """
    # Build the WHERE clause only for filters that were actually provided.
    # Keeping conditions and params in parallel lists guarantees they stay aligned.
    conditions: list[str] = []
    params:     list[str] = []

    if category is not None:
        conditions.append("category = ?")
        params.append(category)
    if urgency is not None:
        conditions.append("urgency = ?")
        params.append(urgency)
    if status is not None:
        conditions.append("status = ?")
        params.append(status)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT * FROM tickets {where_clause} ORDER BY created_at DESC"

    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [dict(row) for row in rows]


def update_ticket(ticket_id: str, fields: dict) -> dict | None:
    """
    Partially update an existing ticket and return the updated row.

    Only the keys present in `fields` are written; everything else is left
    unchanged.  Returns None if the ticket does not exist.

    Args:
        ticket_id: ID of the ticket to update.
        fields:    Dict of column→value pairs to set.  Caller is responsible
                   for validating values before calling this function.
    """
    if not fields:
        # Nothing to do — just return the current state.
        return get_ticket(ticket_id)

    # Build the SET clause dynamically from the provided fields.
    # Using named placeholders (:col) avoids any SQL injection risk even
    # though these values come from a server-side whitelist, not user input.
    set_clause = ", ".join(f"{col} = :{col}" for col in fields)
    sql = f"UPDATE tickets SET {set_clause} WHERE id = :_id"

    params = {**fields, "_id": ticket_id.upper()}

    with _get_conn() as conn:
        cursor = conn.execute(sql, params)

    if cursor.rowcount == 0:
        # No row was updated — ticket doesn't exist.
        return None

    return get_ticket(ticket_id)
