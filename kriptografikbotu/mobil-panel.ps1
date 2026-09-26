# Run after installing Tailscale and signing in on this PC.
# The panel remains bound to localhost; Tailscale Serve exposes it only to this tailnet.
$ErrorActionPreference = 'Stop'
$cli = 'C:\Program Files\Tailscale\tailscale.exe'
if (-not (Test-Path -LiteralPath $cli)) {
    throw 'Tailscale kurulu değil. https://tailscale.com/download adresinden kurup giriş yapın.'
}
try {
    Invoke-WebRequest -Uri 'http://127.0.0.1:8001/app' -UseBasicParsing -TimeoutSec 3 | Out-Null
} catch {
    throw 'Panel çalışmıyor. Önce KAPANIS-BASLAT.bat dosyasını çalıştırın.'
}
$state = & $cli status --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $state.BackendState -ne 'Running') {
    throw 'Tailscale hesabına bu bilgisayarda giriş yapın, sonra betiği yeniden çalıştırın.'
}
& $cli serve --bg 127.0.0.1:8001
if ($LASTEXITCODE -ne 0) {
    throw 'Tailscale Serve açılamadı. Gösterilen HTTPS izin bağlantısını onaylayıp yeniden deneyin.'
}
Write-Host 'Telefon paneli (yalnız aynı Tailscale ağı):'
& $cli serve status
Write-Host 'Telefonda da Tailscale hesabınıza giriş yapıp HTTPS adresine /app ekleyin; tarayıcıdan Ana ekrana ekle seçin.'
