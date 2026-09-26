@echo off
chcp 65001 >nul
title Kapanis - baslatiliyor
set BOT=C:\Users\etemk\OneDrive\Desktop\kriptografikbotu
set WEB=C:\Users\etemk\OneDrive\Desktop\kapanis

echo === Kapanis baslatiliyor ===
echo.
echo [1/5] Eski bot/panel surecleri kapatiliyor (iki bot ayni anda calismasin)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%BOT%\kapanis_surecler.ps1" -Stop
echo.

echo [2/5] MongoDB kontrol ediliyor...
sc query MongoDB | find "RUNNING" >nul
if errorlevel 1 (
    echo   MongoDB calismiyor, baslatiliyor...
    net start MongoDB >nul 2>&1
    sc query MongoDB | find "RUNNING" >nul
    if errorlevel 1 (
        echo   UYARI: MongoDB baslatilamadi. Panel verisi gorunmez; bot yine calisir.
        echo   Cozum: bu dosyaya sag tik - Yonetici olarak calistir.
    ) else (
        echo   MongoDB calisiyor.
    )
) else (
    echo   MongoDB calisiyor.
)
echo.

echo [3/5] Panel arayuzu kontrol ediliyor...
rem Rebuild only when the UI source changed since the last build (takes ~1 minute, once).
powershell -NoProfile -Command "$b='%WEB%\frontend\build\index.html'; if(!(Test-Path $b)){exit 1}; $t=(Get-Item $b).LastWriteTime; $n=Get-ChildItem '%WEB%\frontend\src','%WEB%\frontend\public','%WEB%\frontend\.env' -Recurse -File | Where-Object {$_.LastWriteTime -gt $t} | Select-Object -First 1; if($n){exit 1}else{exit 0}"
if errorlevel 1 (
    echo   Arayuz degismis, derleniyor ^(yaklasik 1 dakika, sadece bu sefer^)...
    pushd "%WEB%\frontend"
    set CI=false
    call npx craco build >"%TEMP%\kapanis_build.log" 2>&1
    popd
    if exist "%WEB%\frontend\build\index.html" (
        echo   Arayuz derlendi.
    ) else (
        echo   UYARI: Derleme basarisiz. Ayrinti: %TEMP%\kapanis_build.log
    )
) else (
    echo   Arayuz guncel.
)
echo.

echo [4/5] Panel API + arayuz baslatiliyor (port 8001)...
start "Kapanis API" /min cmd /k "cd /d %WEB%\backend && .venv\Scripts\python -m uvicorn server:app --host 127.0.0.1 --port 8001"
powershell -NoProfile -Command "for($i=0;$i -lt 30;$i++){try{Invoke-WebRequest http://127.0.0.1:8001/api/ -UseBasicParsing -TimeoutSec 2 | Out-Null; Write-Host '  Panel hazir.'; exit 0}catch{Start-Sleep 1}}; Write-Host '  UYARI: API 30 sn icinde acilmadi, Kapanis API penceresine bak.'"
echo.

echo [5/5] Telegram botu baslatiliyor...
start "Kapanis Bot" /min cmd /k "cd /d %BOT% && .venv\Scripts\python main.py"
echo   Bot penceresi acildi (gorev cubugunda kucuk).
start http://localhost:8001/app
echo.
echo === Hepsi calisiyor ===
echo Panel: http://localhost:8001/app
echo Bot ve API gorev cubugunda kucultulmus pencerelerde. O pencereleri KAPATMA.
echo Hepsini durdurmak icin: KAPANIS-DURDUR.bat
echo.
echo Bu pencere 10 saniye sonra kapanacak.
timeout /t 10 >nul
