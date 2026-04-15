🖥️ ClearDesk — AI-Powered IT Support Ticketing System

A lightweight IT helpdesk web application that automatically classifies and tracks support tickets using AI.

📌 Overview
ClearDesk is a portfolio project built to demonstrate practical IT support, automation, and AI integration skills. It streamlines the support request process by using the Claude AI API to automatically triage incoming tickets — eliminating the need for manual categorisation and reducing response time.
Support staff can submit issues, have them instantly classified, and track them through their full lifecycle via a clean, filterable dashboard.

✨ Features

🤖 AI-Powered Auto-Classification — Automatically assigns a category and urgency level to every ticket on submission
🏷️ Smart Categorisation — Tickets are tagged as Network, Hardware, Software, or Access
🚨 Urgency Detection — Each ticket is rated Low, Medium, or High urgency
📋 Full Ticket Lifecycle Tracking — Status updates from Open → In Progress → Resolved
🔍 Filterable Dashboard — Filter tickets by category, urgency, and status at a glance
🗄️ Persistent Storage — All tickets saved to a local SQLite database
⚡ Lightweight & Fast — No heavy frameworks, runs locally with minimal setup


🛠️ Tech Stack
LayerTechnology - Backend - Python, FlaskAPI , Database - SQLite, Frontend - HTML, CSS, JavaScript, API - Communication REST (Flask-CORS)

📁 Project Structure
cleardesk/
├── app.py              # Flask API routes
├── classifier.py       # Claude AI classification logic
├── db.py               # SQLite database setup and queries
├── requirements.txt    # Python dependencies
├── frontend/
│   └── index.html      # Dashboard and ticket submission UI
└── README.md

🚀 Getting Started
Prerequisites

Python 3.8+
An Anthropic API key

Installation

Clone the repository

bash   git clone https://github.com/yourusername/cleardesk.git
   cd cleardesk

Install dependencies

bash   pip install -r requirements.txt

Set your API key

bash   export API_KEY=your_api_key_here

Run the app

bash   python app.py

Open in your browser

   http://localhost:5000

🖼️ How It Works

A user submits an IT support ticket with a title and description
ClearDesk sends the ticket to the Claude API for analysis
Claude returns a category (Network / Hardware / Software / Access) and urgency (Low / Medium / High)
The ticket is saved to the database and displayed on the dashboard
Support staff can update the ticket status as they work through it


📊 Example Ticket Flow
FieldExampleTitle"Can't connect to VPN from home"Description"Getting a timeout error when trying to connect to the company VPN since this morning."AI Category🌐 NetworkAI Urgency🔴 HighStatusOpen → In Progress → Resolved

💡 Why I Built This
Most IT support roles rely on tools like ServiceNow, Zendesk, or Jira — all of which use automated classification under the hood. ClearDesk was built to demonstrate a hands-on understanding of how these systems work, combining practical IT support knowledge with Python development and AI integration.

📄 License
This project is open source and available under the MIT License.

🙋 About
Built by Miphang Thapa Magar as a portfolio project for IT support and IT operations roles.
🔗 https://www.linkedin.com/in/miphang-thapa-magar-5416a127a/?skipRedirect=true • 📧 miphangthapamagar21@gmail.com
