# GymFit: Gym Management System

A full-stack gym management web app built with FastAPI, MySQL, SQLAlchemy, and vanilla JavaScript.

## Status
Phase 1 complete: project setup, architecture and database design.

## Tech Stack
FastAPI · SQLAlchemy · MySQL · Pydantic · HTML/CSS/JS · Chart.js

## Quick start (Windows)
1. Run `database/schema.sql` in MySQL Workbench.
2. Create the app DB user (see the setup guide) and note its password.
3. In `backend/`: `powershell -ExecutionPolicy Bypass -File .\setup.ps1`
4. Set `DB_PASSWORD` in `backend/.env`.
5. `.\venv\Scripts\Activate.ps1` then `uvicorn app.main:app --reload`
6. Open http://127.0.0.1:8000/health and http://127.0.0.1:8000/docs
