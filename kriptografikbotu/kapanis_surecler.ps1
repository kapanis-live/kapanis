# Finds (and optionally stops) Kapanis processes: the Telegram bot, the panel API and the panel UI.
# Only processes started from these project folders are touched; other Python/Node apps are left alone.
param([switch]$Stop)

$bot = "C:\Users\etemk\OneDrive\Desktop\kriptografikbotu"
$web = "C:\Users\etemk\OneDrive\Desktop\kapanis"

$targets = @()

# Bot and API: the venv launcher python.exe lives inside the project folder.
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ForEach-Object {
    $exe = "$($_.ExecutablePath)"
    $cmd = "$($_.CommandLine)"
    if ($exe.StartsWith($bot, [StringComparison]::OrdinalIgnoreCase) -and $cmd -match "main\.py") {
        $targets += [pscustomobject]@{ Id = $_.ProcessId; Ne = "Bot (main.py)" }
    }
    elseif ($exe.StartsWith($web, [StringComparison]::OrdinalIgnoreCase) -and $cmd -match "server:app") {
        $targets += [pscustomobject]@{ Id = $_.ProcessId; Ne = "Panel API (port 8001)" }
    }
}

# Panel UI: whatever listens on port 3000 (the React dev server).
Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    $targets += [pscustomobject]@{ Id = $_.OwningProcess; Ne = "Panel arayuz (port 3000)" }
}
# Anything still holding the API port (e.g. a python started outside the venv).
Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    if (-not ($targets.Id -contains $_.OwningProcess)) {
        $targets += [pscustomobject]@{ Id = $_.OwningProcess; Ne = "Panel API (port 8001)" }
    }
}

if ($targets.Count -eq 0) {
    Write-Host "Calisan Kapanis sureci yok."
    exit 0
}
foreach ($t in $targets | Sort-Object Id -Unique) {
    if ($Stop) {
        # /T also ends the child python the venv launcher started.
        taskkill /PID $t.Id /T /F *> $null
        Write-Host "Durduruldu: $($t.Ne) [PID $($t.Id)]"
    } else {
        Write-Host "Calisiyor: $($t.Ne) [PID $($t.Id)]"
    }
}
