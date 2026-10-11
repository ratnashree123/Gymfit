# GymFit: Gym Management System

A full-stack gym management web app built with FastAPI, MySQL, SQLAlchemy, and vanilla JavaScript.

## Status
- Phase 1: project setup, architecture, database design (17 tables)
- Phase 2: SQLAlchemy models, bcrypt password hashing, JWT login, role-based access, staff management, audit log
- Phase 3: members (search, filters, soft delete, photos), membership plans, assign / renew / cancel memberships

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
| GET/POST | `/api/plans` | Admin, Receptionist read / Admin write | Membership plans |
| PATCH/DELETE | `/api/plans/{id}` | Admin | Edit / deactivate a plan |
| GET | `/api/members` | Admin, Receptionist, Trainer (own members only) | Search, filter, sort, pages |
| POST | `/api/members` | Admin, Receptionist | Register a member (optionally with a plan) |
| GET/PATCH | `/api/members/{id}` | see rules below | Profile / edit |
| DELETE | `/api/members/{id}` | Admin | Soft delete (+ `/restore`) |
| GET/POST | `/api/members/{id}/memberships` | Admin, Receptionist | History / assign a plan |
| POST | `/api/members/{id}/renew` | Admin, Receptionist | Renew (no lost days) |
| POST | `/api/members/{id}/memberships/{mid}/cancel` | Admin | Cancel a membership |
| POST/GET/DELETE | `/api/members/{id}/photo` | staff | Private profile photo (JPEG/PNG/WEBP, max 2 MB) |

## Membership rules
- A membership is valid on its start and end date (both included): a 30-day plan starting 1 Jan ends 30 Jan.
- Renewing while still covered starts the day after the current period ends, so no days are lost.
- Overlapping periods are rejected; cancelled memberships are ignored.
- Member status (active / upcoming / expired / no_membership / inactive) is calculated from the dates every time, never stored, so it cannot go stale.
- "Today" is today in the gym's timezone (`GYM_TIMEZONE`).

## Who can see what
- Receptionist: register and edit members, but never sees medical notes.
- Trainer: sees only members assigned to them (including their medical notes), read only.
- Admin: everything. Medical notes can only be changed by an Admin.

## Security notes
- Passwords are hashed with bcrypt; hashes are never returned by the API.
- Login is rate-limited (5 failures / 15 min per email + IP).
- The role is read from the database on every request, so deactivating a user takes effect immediately.
- Important changes are written to `audit_logs` (medical notes are never copied into it).
- Photo uploads are checked by their real file signature, renamed randomly, and only served to logged-in staff.

## Tests
From `backend/` with the venv active: `pytest -v` (uses an in-memory SQLite database, not your MySQL data).
