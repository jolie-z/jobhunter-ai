@echo off
chcp 65001 > nul
set PYTHONUTF8=1
echo ==============================================
echo   Starting Auto-JobHunter
echo ==============================================
echo.

echo [1/2] Starting Backend (FastAPI)...
start "Backend" cmd /k "cd backend && call .venv\Scripts\activate && fastapi dev app/main.py"

echo [2/2] Starting Frontend (Next.js)...
start "Frontend" cmd /k "cd frontend && npm install && npm run dev"

echo.
echo Both services are starting in new terminal windows.
echo Frontend will be available at: http://localhost:3000
echo Backend will be available at:  http://localhost:8000
echo ==============================================
pause
