@echo off
REM Affiliate-Dashboard aktualisieren: Daten einlesen und dashboard.html erzeugen.
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m affiliate_dashboard.run %*
) else (
    python -m affiliate_dashboard.run %*
)

echo.
pause
