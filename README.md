# GymFit: Gym Management System

A full-stack gym management web app built with FastAPI, MySQL, SQLAlchemy, and vanilla JavaScript.

## Status
- Phase 1: project setup, architecture, database design (17 tables)
- Phase 2: SQLAlchemy models, bcrypt password hashing, JWT login, role-based access, staff management, audit log
- Phase 3: members (search, filters, soft delete, photos), membership plans, assign / renew / cancel memberships
- Phase 4: invoices (discount + tax), manual payments with partial payments, receipts, revenue reports, CSV export
- Phase 5: check-in / check-out, access rules, who is inside, forgotten check-outs, corrections with audit trail, attendance reports
- Phase 6: equipment inventory, damage reports, maintenance jobs and history, reminders, repair costs, inventory report + CSV
- Phase 7: workout plans and exercises (by day and muscle group), fitness goals, body measurements, progress over time with BMI

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
| GET/POST | `/api/invoices` | Admin, Receptionist | List / search / overdue filter; create personal-training or one-off bills |
| GET | `/api/invoices/summary` | Admin, Receptionist | Money still owed (per member or everyone) |
| GET | `/api/invoices/{id}` | Admin, Receptionist | Invoice with its payments |
| POST | `/api/invoices/{id}/payments` | Admin, Receptionist | Record a payment (cash, UPI, card, bank transfer) |
| POST | `/api/invoices/{id}/cancel` | Admin | Cancel a one-off invoice that has no payments |
| GET | `/api/payments` | Admin, Receptionist | Payment history: search by member, date, receipt / transaction id |
| GET | `/api/payments/{id}/receipt` and `/receipt.html` | Admin, Receptionist | Receipt data / printable receipt page |
| GET | `/api/payments/export.csv` | Admin | CSV download for a date range |
| GET | `/api/reports/revenue` | Admin | Daily, monthly or yearly revenue (chart-ready) |
| GET | `/api/attendance/lookup?search=` | Admin, Receptionist | Desk search: is the member inside, may they enter? |
| POST | `/api/attendance/check-in` | Admin, Receptionist | Check a member in (Admin may override a refusal with a reason) |
| POST | `/api/attendance/check-out` | Admin, Receptionist | Check a member out, records the visit length |
| GET | `/api/attendance/inside` | staff (trainers: own members) | Who is inside right now |
| GET | `/api/attendance` | staff (trainers: own members) | History by member, status, day / week / month or date range |
| GET | `/api/attendance/report` | Admin, Receptionist | Visits, unique members, average stay, peak hour / day |
| GET | `/api/attendance/export.csv` | Admin | CSV download for a date range |
| POST | `/api/attendance/close-stale` | Admin, Receptionist | Close visits nobody checked out |
| PATCH | `/api/attendance/{id}` | Admin | Correct times (reason required, old values audited) |
| POST | `/api/attendance/{id}/remove` | Admin | Remove a mistaken check-in (kept in the audit log) |
| GET | `/api/equipment` | staff | Search, filter (category, status, condition, urgent / soon), sort, pages |
| POST | `/api/equipment` | Admin | Add an item (code `EQ-0001`...) |
| GET/PATCH | `/api/equipment/{id}` | staff read / Admin edit | Profile with next maintenance and repair costs (costs: Admin only) |
| POST | `/api/equipment/{id}/archive` and `/restore` | Admin | Hide / show an item (nothing is ever deleted) |
| POST | `/api/equipment/{id}/report-damage` | any staff | Flag a broken item; opens a repair job |
| GET | `/api/equipment/categories` | staff | Existing categories for a dropdown |
| GET | `/api/equipment/report` and `/export.csv` | Admin | Inventory report / CSV download |
| POST | `/api/equipment/{id}/maintenance` | Admin | Schedule a routine, repair or inspection job |
| GET | `/api/maintenance` and `/{id}` | Admin, Receptionist | Maintenance history (costs: Admin only) |
| GET | `/api/maintenance/reminders` | Admin, Receptionist | Urgent (damaged / overdue) and soon-due equipment |
| POST | `/api/maintenance/{id}/start`, `/complete`, `/cancel` | Admin | Move a job through its life cycle |
| PATCH | `/api/maintenance/{id}` | Admin | Edit a scheduled or in-progress job |
| GET/POST | `/api/workouts/plans` | Admin, Trainer (own members) | List / create a workout plan (optionally with exercises) |
| GET/PATCH | `/api/workouts/plans/{id}` | Admin, Trainer (own members) | Plan with exercises grouped by day; edit, complete or archive |
| POST | `/api/workouts/plans/{id}/exercises` and `/reorder` | Admin, Trainer (own members) | Add an exercise / change the order within a day |
| PATCH/DELETE | `/api/workouts/exercises/{id}` | Admin, Trainer (own members) | Edit / remove an exercise |
| GET | `/api/workouts/muscle-groups` | Admin, Trainer | Suggested muscle groups |
| GET/POST | `/api/progress` | Admin, Trainer (own members) | Body measurements: list / record |
| GET/PATCH/DELETE | `/api/progress/{id}` | Admin, Trainer (own members) | One record |
| GET | `/api/progress/members/{id}/series` | Admin, Trainer (own members) | Chart-ready points with BMI and the change since the first record |
| GET | `/api/progress/members/{id}/summary` | Admin, Trainer (own members) | Goal, active plan, first and latest record, BMI, changes |

## Membership rules
- A membership is valid on its start and end date (both included): a 30-day plan starting 1 Jan ends 30 Jan.
- Renewing while still covered starts the day after the current period ends, so no days are lost.
- Overlapping periods are rejected; cancelled memberships are ignored.
- Member status (active / upcoming / expired / no_membership / inactive) is calculated from the dates every time, never stored, so it cannot go stale.
- "Today" is today in the gym's timezone (`GYM_TIMEZONE`).

## Billing rules
- Assigning or renewing a plan creates an invoice in the same transaction. It starts as `pending`.
- An invoice becomes `partial` or `paid` ONLY when payments are recorded; nothing is ever marked paid automatically.
- Total = (price - discount) + tax. Tax comes from the `tax_percent` setting and is charged on the discounted price. All money is `Decimal`, rounded half-up to 2 places.
- A free (0.00) membership creates no invoice.
- Payments are manual entries (`verification_type = manual`); the API cannot create "verified online" payments. UPI, card and bank transfers need a reference number, and the same reference cannot be used twice.
- Payments are never edited or deleted. Refunds are not supported yet, so a membership or invoice that has payments cannot be cancelled.
- Receptionists can give at most 10% discount (setting `max_receptionist_discount_percent`); Admins have no limit.
- Reports group by the gym's local dates, and CSV cells that start with `= + - @` are neutralised against spreadsheet formula injection.

## Attendance rules
- Entry needs: an active member, a membership covering today (plus `grace_period_days`), and a fully paid membership fee unless `allow_checkin_unpaid` is on. A free plan has no fee to pay.
- Check-in and check-out times always come from the server clock, never from the client.
- A member can have only ONE open visit. The database enforces it (unique index), not just the code, so two desks clicking at once cannot create a duplicate.
- A visit still open after `auto_checkout_hours` (default 8) is a forgotten check-out: it is closed as `auto_closed` (the stay is capped at that many hours) the next time the member checks in, or by `close-stale`. Auto-closed visits are left out of the average stay.
- Only an Admin can override a refused check-in (reason required) or correct / remove a record. Corrections are saved with the old values in `audit_logs`.
- Times typed in a correction without an offset are read as the gym's local time; reports group by local dates (a 00:30 visit counts on the new day).

## Equipment and maintenance rules
- Equipment status is only `available`, `damaged` or `under_maintenance`. `under_maintenance` is never typed in: starting a job sets it, completing or cancelling a job moves it on. A completed repair makes the item available; a routine service on a broken item does not.
- A job is `scheduled`, `in_progress`, `completed` or `cancelled`. Completed and cancelled jobs are locked history. There is no delete for equipment or maintenance: items are archived, jobs are cancelled.
- A damage report (any staff member) marks the item damaged and opens a repair job so the Admin sees it in the reminders.
- Urgent = damaged, or maintenance overdue. Soon = due within `maintenance_alert_days` (default 7) or in poor condition. The list filter and the reminders use the same rules.
- Completing a job records the cost, sets `last_maintenance_date`, clears a next date that the job satisfied (or sets the date you give), and can update the condition.
- `purchase_price` is the price of ONE item; the value of a record is price x quantity. Prices and costs are visible to Admins only.
- If only one of several identical machines is broken, add it as its own record, because status belongs to the whole record.

## Workout and progress rules
- Admins and Trainers only; a Trainer sees only the members assigned to them (anyone else's member answers 404). Receptionists have no access to workout or body data. If a member is reassigned, access moves to the new trainer.
- A member has at most ONE active plan. Completing a plan closes it (end date = today). Completed and archived plans are read-only until set back to active. Plans are archived, never deleted.
- An exercise has a day (1 to 7), a muscle group, and either sets AND reps or a duration. At most 30 exercises per day; `reorder` sets the order inside a day.
- Every measurement is optional (voluntary), but a record cannot be empty and a member has at most one record per day. Values must be realistic (for example weight 20 to 400 kg).
- BMI uses the latest known height, even if it was measured before the period you are looking at. It is an adult indicator, not a diagnosis.
- Measurements can be erased. The audit log records only WHICH fields changed, never the values or notes.

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
