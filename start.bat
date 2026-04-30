@echo off
chcp 65001 > nul
echo ========================================
echo Starting Multi-Agent Learning System
echo ========================================
echo.

python --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found
    pause
    exit /b 1
)

echo [1/2] Starting backend (http://localhost:8000)...
start "Backend" cmd /k "uvicorn backend.main:app --reload --port 8000"

echo [2/2] Starting frontend (http://localhost:8501)...
timeout /t 3 > nul
start "Frontend" cmd /k "streamlit run streamlit_app/app.py"

echo.
echo ========================================
echo Done!
echo   Backend: http://localhost:8000
echo   Frontend: http://localhost:8501
echo.
echo Press any key to open browser...
echo ========================================
pause > nul
start http://localhost:8501