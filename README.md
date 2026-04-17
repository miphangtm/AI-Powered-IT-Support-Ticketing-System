# ClearDesk — AI-Powered IT Support Ticketing

ClearDesk is a full-stack IT support ticketing system that uses Google Gemini to automatically triage incoming tickets — assigning a category, urgency level, and a suggested resolution — so IT staff spend time solving problems instead of sorting them.

Tickets are submitted through a clean, professional web interface, stored in SQLite, and displayed in a live dashboard with colour-coded badges and inline status controls. No JavaScript frameworks. No build step. Just a readable, well-structured codebase.

---

## Features

- **AI triage on every ticket** — Gemini classifies each submission into a category (Network / Hardware / Software / Access / Other) and urgency (Low / Medium / High), and suggests a resolution step
- **Graceful fallback** — if the AI call fails, the ticket is still created with safe defaults; the user never sees a 500 error
- **Rich ticket dashboard** — filterable table with colour-coded category, urgency, and status badges
- **Inline status management** — update ticket status directly from the table row or the detail panel without leaving the page
- **Persistent filters** — active filters survive status updates and new submissions
- **Empty-state UX** — context-aware copy and icon when no tickets match the current view
- **Accessibility** — `aria-live` regions, `aria-label` on interactive elements, keyboard-navigable rows

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend API | Python 3.11+, Flask, Flask-CORS |
| AI / LLM | Google Gemini (`gemini-2.5-flash`) via `google-genai` SDK — free tier |
| Database | SQLite 3 (WAL mode, parameterised queries, no ORM) |
| Frontend | Vanilla HTML5, CSS3 (custom properties), JavaScript (ES2020) |

---

## Project Structure

```
ClearDesk/
├── backend/
│   ├── app.py           # Flask routes, request validation, error handlers
│   ├── classifier.py    # Gemini AI wrapper — classification + resolution
│   ├── db.py            # SQLite persistence layer (all DB access lives here)
│   ├── .env.example     # Environment variable template
│   └── cleardesk.db     # Created automatically on first run
├── frontend/
│   ├── index.html       # Single-page application shell
│   ├── css/
│   │   └── style.css    # Design tokens, layout, components, responsive rules
│   └── js/
│       └── app.js       # All frontend logic — fetch, render, filter, form
├── requirements.txt
├── README.md
├── DOCUMENTATION.txt    # Beginner-friendly explanation of every file and concept
└── .gitignore
```

---

## Getting Started

### Prerequisites

- Python 3.11 or later
- A [Google Gemini API key](https://aistudio.google.com/app/apikey) — free tier, no credit card required

### Setup

1. **Clone the repository:**
   ```bash
   git clone <repo-url>
   cd ClearDesk
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate      # macOS / Linux
   venv\Scripts\activate         # Windows
   ```

3. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Add your API key:**
   ```bash
   cp backend/.env.example backend/.env
   # Open backend/.env and set GEMINI_API_KEY=AIza...
   # Get a free key at https://aistudio.google.com/app/apikey
   ```

5. **Start the backend server:**
   ```bash
   cd backend
   python app.py
   # Flask starts on http://localhost:5000
   ```

6. **Open the frontend:**
   Open `frontend/index.html` directly in your browser, or serve the `frontend/` folder with any static file server:
   ```bash
   # Python one-liner — run from the project root
   python -m http.server 8080 --directory frontend
   # Then visit http://localhost:8080
   ```

The SQLite database (`backend/cleardesk.db`) is created automatically on first run — no migration step needed.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/tickets` | List all tickets, newest first. Optional query params: `category`, `urgency`, `status` |
| `POST` | `/api/tickets` | Create a ticket. Body: `{ title, description, submitter? }` |
| `GET` | `/api/tickets/<id>` | Fetch a single ticket by ID |
| `PATCH` | `/api/tickets/<id>` | Update `status`, `urgency`, or `category` |

All responses (including errors) are JSON. Invalid filter values return `400` with an explanation rather than a silent empty list.

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | Yes | Your Google Gemini API key (free at aistudio.google.com) |
| `DATABASE_PATH` | No | Override the SQLite file path (useful for tests) |

---

## Portfolio Note

ClearDesk was built as a portfolio project to demonstrate full-stack development skills relevant to IT support and helpdesk engineering roles. It covers the complete lifecycle of a support ticket — from submission through AI-assisted triage to resolution — using real-world patterns: a layered backend architecture (routing / AI / persistence separated by concern), safe SQL parameterisation, graceful AI fallback, and a polished accessible frontend with no external dependencies.
