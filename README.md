# GymFit: Gym Management System

A full-stack gym management web app built with FastAPI, MySQL, SQLAlchemy, and vanilla JavaScript.

## Status
- Phase 1: project setup, architecture, database design (17 tables)
- Phase 2: SQLAlchemy models, bcrypt password hashing, JWT login, role-based access, staff management, audit log

## Tech Stack
FastAPI · SQLAlchemy · MySQL · Pydantic · PyJWT · bcrypt · HTML/CSS/JS · Chart.js

## Quick start (Windows)
1. Run `database/schema.sql` in MySQL Workbench.
2. Create the app DB user (see the setup guide) and note its password.
3. In `backend/`: `powershell -ExecutionPolicy Bypass -File .\setup.ps1`
4. Edit `backend/.env`: set `DB_PASSWORD` and the three `FIRST_ADMIN_*` values.
5. `.\venv\Scripts\Activate.ps1`
6. `python -m app.scripts.create_admin` (creates the first Admin, run once)
7. `uvicorn app.main:app --reload`
8. Open http://127.0.0.1:8000/docs, click **Authorize**, log in with the admin email and password.

## API (so far)
| Method | URL | Who | Purpose |
|---|---|---|---|
| POST | `/api/auth/login` | anyone | Log in, returns a token |
| GET | `/api/auth/me` | any logged-in user | Current user |
| POST | `/api/auth/logout` | any logged-in user | Records the logout |
| POST | `/api/auth/change-password` | any logged-in user | Change own password |
| GET | `/api/staff` | Admin | List staff (search, filter, sort, pages) |
| POST | `/api/staff` | Admin | Create staff account |
| GET/PATCH/DELETE | `/api/staff/{id}` | Admin | View, edit, deactivate |
| POST | `/api/staff/{id}/reset-password` | Admin | Set a new password |
| GET | `/api/staff/trainers` | Admin, Receptionist | Active trainers (no salary) |

## Security notes
- Passwords are hashed with bcrypt; hashes are never returned by the API.
- Login is rate-limited (5 failures / 15 min per email + IP).
- The role is read from the database on every request, so deactivating a user takes effect immediately.
- Important changes are written to `audit_logs`.

## Tests
From `backend/` with the venv active: `pytest -v` (uses an in-memory SQLite database, not your MySQL data).
