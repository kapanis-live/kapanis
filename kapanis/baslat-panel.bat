@echo off
rem Kapanis web panel: API (port 8001) + arayuz (port 3000). Botu ayrica baslat.bat ile ac.
cd /d "%~dp0backend"
start "Kapanis API" cmd /k ".venv\Scripts\python -m uvicorn server:app --host 127.0.0.1 --port 8001"
cd /d "%~dp0frontend"
start "Kapanis Panel" cmd /k "npm start"
timeout /t 15 >nul
start http://localhost:3000
