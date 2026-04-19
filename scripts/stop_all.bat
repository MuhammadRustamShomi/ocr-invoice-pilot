@echo off
echo Stopping OCR Invoice Pilot...
taskkill /f /im uvicorn.exe 2>nul
taskkill /f /fi "WINDOWTITLE eq Invoice Watcher" 2>nul
echo Done. All services stopped.
pause
