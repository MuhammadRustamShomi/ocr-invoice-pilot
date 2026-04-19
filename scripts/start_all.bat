@echo off
echo Starting OCR Invoice Pilot...
echo.
echo [1/3] Activating virtual environment...
call "%~dp0..\venv\Scripts\activate"
echo.
echo [2/3] Starting OCR API on port 8000...
start "OCR API" cmd /k "cd /d "%~dp0.." && set PYTHONUTF8=1 && venv\Scripts\uvicorn api.main:app --host 127.0.0.1 --port 8000"
timeout /t 3 /nobreak > nul
echo.
echo [3/3] Starting Invoice Watcher...
start "Invoice Watcher" cmd /k "cd /d "%~dp0.." && venv\Scripts\python watcher\run_watcher.py"
echo.
echo All services started!
echo  - API:       http://127.0.0.1:8000
echo  - API Docs:  http://127.0.0.1:8000/docs
echo  - Dashboard: Run "streamlit run dashboard\app.py" separately
echo.
pause
