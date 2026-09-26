@echo off
chcp 65001 >nul
title Kapanis - durduruluyor
echo === Kapanis durduruluyor ===
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\etemk\OneDrive\Desktop\kriptografikbotu\kapanis_surecler.ps1" -Stop
echo.
echo Bot, API ve Panel durdu. MongoDB arka planda kalir (kaynak harcamaz).
timeout /t 5 >nul
