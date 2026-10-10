# One-click backend setup for Windows. Run from the gymfit\backend folder:
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
$ErrorActionPreference = "Stop"

if (-not (Test-Path "venv")) {
    Write-Host "Creating virtual environment..."
    python -m venv venv
}

Write-Host "Installing packages..."
& .\venv\Scripts\python.exe -m pip install --upgrade pip
& .\venv\Scripts\python.exe -m pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
    $key = & .\venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
    (Get-Content .env) -replace 'SECRET_KEY=.*', "SECRET_KEY=$key" | Set-Content .env
    Write-Host "Created .env with a fresh SECRET_KEY. Now open .env and set DB_PASSWORD."
}

Write-Host ""
Write-Host "Setup done. Next:"
Write-Host "  1. Edit backend\.env and set DB_PASSWORD"
Write-Host "  2. Run database\schema.sql in MySQL Workbench"
Write-Host "  3. .\venv\Scripts\Activate.ps1  then  uvicorn app.main:app --reload"
