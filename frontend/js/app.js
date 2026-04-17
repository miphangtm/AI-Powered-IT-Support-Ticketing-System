/**
 * ClearDesk — Frontend Application
 * ----------------------------------
 * Vanilla JS SPA that communicates with the Flask backend REST API.
 * No build step or framework required — runs directly in the browser.
 */

const API_BASE = "http://localhost:5000/api";

// ---------------------------------------------------------------------------
// DOM references — cached once at module load to avoid repeated lookups.
// ---------------------------------------------------------------------------

const form        = document.getElementById("ticket-form");
const submitBtn   = document.getElementById("submit-btn");
const ticketsList = document.getElementById("tickets-list");   // <tbody>
const ticketCount = document.getElementById("ticket-count");
const detailPanel = document.getElementById("ticket-detail");
const filterBar   = document.getElementById("filter-bar");
const toastEl     = document.getElementById("toast");

// ---------------------------------------------------------------------------
// Application state
// ---------------------------------------------------------------------------

/** ID of the currently selected ticket, or null when none is selected. */
let selectedId = null;

/** Timer handle used to auto-dismiss the toast notification. */
let toastTimer = null;

/**
 * Active filter values for each dimension.
 * null means "show all" — no query param is sent for that dimension.
 * These persist across list reloads so filters survive status updates.
 */
const activeFilters = {
  category: null,
  urgency:  null,
  status:   null,
};

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

/**
 * Escape a string for safe insertion into innerHTML.
 * Prevents XSS when rendering user-supplied ticket content.
 *
 * @param {string} str - Raw input string.
 * @returns {string} HTML-entity-encoded string.
 */
function escHtml(str = "") {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * Format an ISO-8601 timestamp into a human-readable local date/time string.
 *
 * @param {string} iso - UTC ISO timestamp, e.g. "2025-06-01T14:30:00Z".
 * @returns {string} Locale-formatted string, e.g. "Jun 1, 2025, 02:30 PM".
 */
function formatDate(iso) {
  return new Date(iso).toLocaleString(undefined, {
    month:  "short",
    day:    "numeric",
    year:   "numeric",
    hour:   "2-digit",
    minute: "2-digit",
  });
}

// ---------------------------------------------------------------------------
// Badge renderers
// ---------------------------------------------------------------------------

/**
 * Render a coloured category badge.
 * CSS class: badge-category-{Network|Hardware|Software|Access|Other}
 *
 * @param {string} category
 */
function categoryBadge(category) {
  return `<span class="badge badge-category-${escHtml(category)}">${escHtml(category)}</span>`;
}

/**
 * Render a coloured urgency badge.
 * CSS class: badge-urgency-{Low|Medium|High}
 *
 * @param {string} urgency
 */
function urgencyBadge(urgency) {
  return `<span class="badge badge-urgency-${escHtml(urgency)}">${escHtml(urgency)}</span>`;
}

/**
 * Render a coloured status badge.
 * Spaces are stripped so "In Progress" → badge-status-InProgress.
 *
 * @param {string} status
 */
function statusBadge(status) {
  const cssKey = status.replace(/\s+/g, "");
  return `<span class="badge badge-status-${escHtml(cssKey)}">${escHtml(status)}</span>`;
}

// ---------------------------------------------------------------------------
// Toast notifications
// ---------------------------------------------------------------------------

/**
 * Show a brief toast message at the bottom-right of the screen.
 * Auto-dismisses after 3 seconds; resetting the timer on rapid calls.
 *
 * @param {string} message - Plain-text message to display.
 */
function showToast(message) {
  toastEl.textContent = message;
  toastEl.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.remove("show"), 3000);
}

// ---------------------------------------------------------------------------
// Filter bar
// ---------------------------------------------------------------------------

/**
 * Handle all filter button clicks via event delegation on the filter bar.
 *
 * Each .filter-btns wrapper carries data-filter-type (the dimension).
 * Each button carries data-value (the value to filter on, or "" for "All").
 *
 * Keeping a single listener rather than one per button avoids having to
 * re-attach listeners every time the list re-renders.
 */
filterBar.addEventListener("click", (e) => {
  const btn = e.target.closest(".filter-btn");
  if (!btn) return;

  // The dimension (category / urgency / status) lives on the parent container.
  const group = btn.closest(".filter-btns");
  const type  = group?.dataset.filterType;
  if (!type) return;

  // null = "All" (no filter applied); any truthy string = specific value.
  const value = btn.dataset.value || null;

  // Update active class within this group only.
  group.querySelectorAll(".filter-btn").forEach((b) => b.classList.remove("active"));
  btn.classList.add("active");

  // Persist the selection and re-fetch from the API with updated params.
  activeFilters[type] = value;
  loadTickets();
});

// ---------------------------------------------------------------------------
// Ticket list
// ---------------------------------------------------------------------------

/**
 * Build a URLSearchParams string from the current activeFilters state.
 * Only dimensions with a non-null value produce a query parameter.
 *
 * @returns {string} e.g. "?urgency=High&status=Open", or "" when no filters.
 */
function buildFilterQuery() {
  const params = new URLSearchParams();
  if (activeFilters.category) params.set("category", activeFilters.category);
  if (activeFilters.urgency)  params.set("urgency",  activeFilters.urgency);
  if (activeFilters.status)   params.set("status",   activeFilters.status);
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

/**
 * Fetch tickets from the API (with active filters) and re-render the table.
 * Displays a user-friendly error row if the backend is unreachable.
 */
async function loadTickets() {
  try {
    const res = await fetch(`${API_BASE}/tickets${buildFilterQuery()}`);

    if (!res.ok) throw new Error(`Server returned ${res.status}`);

    const tickets = await res.json();
    renderList(tickets);
  } catch {
    ticketsList.innerHTML = `
      <tr>
        <td colspan="5">
          <p class="empty-state">Could not reach the backend — is Flask running on port 5000?</p>
        </td>
      </tr>`;
  }
}

/**
 * Render the ticket table body from an array of ticket objects.
 *
 * Each row has:
 *  - Title + submitter sub-line
 *  - Category badge
 *  - Urgency badge
 *  - Inline status <select> (stopPropagation prevents row-click on interaction)
 *  - Created date
 *
 * Clicking anywhere else on the row opens the detail panel.
 *
 * @param {Array<Object>} tickets - Ticket objects from the API.
 */
function renderList(tickets) {
  ticketCount.textContent = tickets.length;

  const anyFilterActive = Object.values(activeFilters).some(Boolean);

  if (tickets.length === 0) {
    // Inbox SVG icon — Feather icon set, MIT licence.
    // stroke="currentColor" inherits the empty-state text colour from CSS.
    const inboxIcon = `
      <svg width="48" height="48" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" stroke-width="1.2"
           stroke-linecap="round" stroke-linejoin="round"
           aria-hidden="true">
        <polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/>
        <path d="M5.45 5.11L2 12v6a2 2 0 002 2h16a2 2 0 002-2v-6
                 l-3.45-6.89A2 2 0 0016.76 4H7.24a2 2 0 00-1.79 1.11z"/>
      </svg>`;

    const title = anyFilterActive
      ? "No tickets match your filters"
      : "No tickets yet";

    const body = anyFilterActive
      ? "Try adjusting or clearing the filters above."
      : "Submit your first IT support ticket using the form on the left.";

    ticketsList.innerHTML = `
      <tr>
        <td colspan="5">
          <div class="empty-state">
            <div class="empty-state-icon">${inboxIcon}</div>
            <p class="empty-state-title">${title}</p>
            <p class="empty-state-body">${body}</p>
          </div>
        </td>
      </tr>`;
    return;
  }

  ticketsList.innerHTML = tickets
    .map(
      (t) => `
        <tr
          class="ticket-row${t.id === selectedId ? " selected" : ""}"
          data-id="${escHtml(t.id)}"
          onclick="selectTicket('${escHtml(t.id)}')"
          tabindex="0"
          aria-label="View ticket ${escHtml(t.id)}: ${escHtml(t.title)}"
        >
          <td class="ticket-col-title">
            <div class="ticket-title">${escHtml(t.title)}</div>
            <div class="ticket-submitter">#${escHtml(t.id)} &middot; ${escHtml(t.submitter)}</div>
          </td>
          <td class="ticket-col-badge">${categoryBadge(t.category)}</td>
          <td class="ticket-col-badge">${urgencyBadge(t.urgency)}</td>

          <!--
            stopPropagation on the cell prevents the row onclick (selectTicket)
            from firing when the user clicks or changes the status dropdown.
          -->
          <td class="ticket-col-status" onclick="event.stopPropagation()">
            <select
              class="status-inline-select"
              aria-label="Update status for ticket ${escHtml(t.id)}"
              onchange="updateStatus('${escHtml(t.id)}', this.value)"
            >
              ${["Open", "In Progress", "Resolved"]
                .map((s) => `<option value="${s}"${s === t.status ? " selected" : ""}>${s}</option>`)
                .join("")}
            </select>
          </td>

          <td class="ticket-col-date">${formatDate(t.created_at)}</td>
        </tr>
      `
    )
    .join("");
}

// ---------------------------------------------------------------------------
// Ticket detail panel
// ---------------------------------------------------------------------------

/**
 * Select a ticket: highlight its row and fetch + render the full detail panel.
 *
 * The row highlight is applied immediately (before the fetch completes) so
 * the UI feels responsive even on a slow connection.
 *
 * @param {string} id - Ticket ID to select.
 */
async function selectTicket(id) {
  selectedId = id;

  // Toggle the selected class on all rows immediately.
  // Targets .ticket-row (table rows) rather than the old .ticket-item divs.
  document.querySelectorAll(".ticket-row").forEach((el) => {
    el.classList.toggle("selected", el.dataset.id === id);
  });

  try {
    const res = await fetch(`${API_BASE}/tickets/${id}`);

    if (!res.ok) throw new Error(`Server returned ${res.status}`);

    const ticket = await res.json();
    renderDetail(ticket);
  } catch {
    showToast("Failed to load ticket details.");
  }
}

/**
 * Populate the detail panel with a single ticket's full information.
 * The panel is shown by adding the .visible class.
 *
 * @param {Object} t - Full ticket object from the API.
 */
function renderDetail(t) {
  detailPanel.classList.add("visible");

  detailPanel.innerHTML = `
    <div class="detail-header">
      <div>
        <div class="detail-title">${escHtml(t.title)}</div>
        <div class="detail-id">
          #${escHtml(t.id)}
          &middot; Submitted by ${escHtml(t.submitter)}
          &middot; ${formatDate(t.created_at)}
        </div>
      </div>
      <div class="detail-badges">
        ${categoryBadge(t.category)}
        ${urgencyBadge(t.urgency)}
        ${statusBadge(t.status)}
      </div>
    </div>

    <div class="detail-section">
      <div class="detail-section-label">Description</div>
      <div class="detail-section-body">${escHtml(t.description)}</div>
    </div>

    <!-- Purple AI box signals generated content vs. human-entered fields -->
    <div class="detail-section ai-box">
      <div class="detail-section-label">AI Suggested Resolution</div>
      <div class="detail-section-body">${escHtml(t.suggested_resolution)}</div>
    </div>

    <div class="status-select">
      <label for="status-sel">Update status:</label>
      <select id="status-sel" onchange="updateStatus('${escHtml(t.id)}', this.value)">
        ${["Open", "In Progress", "Resolved"]
          .map((s) => `<option value="${s}"${s === t.status ? " selected" : ""}>${s}</option>`)
          .join("")}
      </select>
    </div>
  `;
}

// ---------------------------------------------------------------------------
// Status updates
// ---------------------------------------------------------------------------

/**
 * PATCH the ticket status via the API, then refresh the list and (if the
 * updated ticket is currently open) re-render the detail panel so its badge
 * and status select stay in sync.
 *
 * @param {string} id     - Ticket ID to update.
 * @param {string} status - New status value.
 */
async function updateStatus(id, status) {
  try {
    const res = await fetch(`${API_BASE}/tickets/${id}`, {
      method:  "PATCH",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ status }),
    });

    if (!res.ok) throw new Error(`Server returned ${res.status}`);

    showToast(`Status updated to "${status}"`);

    // Refresh the table (preserves active filters via buildFilterQuery()).
    await loadTickets();

    // If the updated ticket's detail panel is open, re-fetch it so the
    // status badge and select inside the panel reflect the new value.
    if (selectedId === id) {
      await selectTicket(id);
    }
  } catch {
    showToast("Failed to update status.");
  }
}

// ---------------------------------------------------------------------------
// Ticket submission form
// ---------------------------------------------------------------------------

/**
 * Show a validation error on a single field.
 * Adds the red-border class and injects a message element below the input.
 *
 * @param {HTMLElement} field   - The input or textarea element.
 * @param {string}      message - Error text to display beneath the field.
 */
function showFieldError(field, message) {
  field.classList.add("input-error");

  // Avoid duplicate messages if the user submits repeatedly.
  const existing = field.parentElement.querySelector(".field-error");
  if (existing) return;

  const el = document.createElement("p");
  el.className = "field-error";
  el.setAttribute("role", "alert");
  el.innerHTML = `
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" stroke-width="2.5" stroke-linecap="round"
         stroke-linejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="10"/>
      <line x1="12" y1="8" x2="12" y2="12"/>
      <line x1="12" y1="16" x2="12.01" y2="16"/>
    </svg>
    ${escHtml(message)}`;
  field.parentElement.appendChild(el);
}

/**
 * Remove the validation error state from a field.
 * Called as soon as the user starts editing the field.
 *
 * @param {HTMLElement} field - The input or textarea element.
 */
function clearFieldError(field) {
  field.classList.remove("input-error");
  const msg = field.parentElement.querySelector(".field-error");
  if (msg) msg.remove();
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();

  const titleEl       = document.getElementById("title");
  const descriptionEl = document.getElementById("description");

  const title       = titleEl.value.trim();
  const description = descriptionEl.value.trim();
  const submitter   = document.getElementById("submitter").value.trim() || "Anonymous";

  // Validate required fields and surface errors inline rather than silently
  // doing nothing — gives the user clear feedback on what to fix.
  let hasError = false;
  if (!title) {
    showFieldError(titleEl, "Issue title is required.");
    hasError = true;
  }
  if (!description) {
    showFieldError(descriptionEl, "Description is required.");
    hasError = true;
  }
  if (hasError) return;

  // Disable all form controls and activate the loading state.
  // .form--loading reveals the AI thinking banner and dims the inputs via CSS.
  form.classList.add("form--loading");
  form.querySelectorAll("input, textarea").forEach((el) => (el.disabled = true));
  submitBtn.disabled = true;
  submitBtn.innerHTML = `<span class="spinner" aria-hidden="true"></span> Submitting…`;

  try {
    const res = await fetch(`${API_BASE}/tickets`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ title, description, submitter }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `Server error (${res.status})`);
    }

    const ticket = await res.json();

    form.reset();
    // Clear any lingering error states left from a previous failed attempt.
    [titleEl, descriptionEl].forEach(clearFieldError);
    showToast(`Ticket #${ticket.id} created — Urgency: ${ticket.urgency}`);

    // Reload the list (with current filters), then open the new ticket's detail.
    await loadTickets();
    selectTicket(ticket.id);
  } catch (err) {
    showToast(err.message || "Failed to create ticket.");
  } finally {
    // Always restore all controls regardless of success or failure.
    form.classList.remove("form--loading");
    form.querySelectorAll("input, textarea").forEach((el) => (el.disabled = false));
    submitBtn.disabled = false;
    submitBtn.innerHTML = "Submit Ticket";
  }
});

// ---------------------------------------------------------------------------
// Inline validation — clear error state as soon as the user edits the field.
// ---------------------------------------------------------------------------
["title", "description"].forEach((id) => {
  document.getElementById(id).addEventListener("input", (e) => {
    clearFieldError(e.target);
  });
});

// ---------------------------------------------------------------------------
// Bootstrap — load tickets on page load.
// ---------------------------------------------------------------------------
loadTickets();
