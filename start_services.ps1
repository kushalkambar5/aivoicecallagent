#!/usr/bin/env pwsh
# ============================================================
# start_services.ps1
# Starts all components of the AI Voice Calling Agent:
#   - STT Server (Qwen3-ASR-1.7B) on port 8001
#   - TTS Server (CosyVoice3)      on port 8002
#   - Dograh stack (Docker)        on port 3010
#
# Prerequisites: Run setup_cosyvoice.ps1 once first.
# ============================================================

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

# --- Load .env -------------------------------------------------
$EnvFile = "$Root\.env"
if (Test-Path $EnvFile) {
    Write-Host "[.env] Loading environment from $EnvFile" -ForegroundColor Gray
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match "^\s*([^#][^=]*)=(.*)$") {
            $key = $matches[1].Trim()
            $val = $matches[2].Trim()
            [System.Environment]::SetEnvironmentVariable($key, $val, "Process")
        }
    }
} else {
    Write-Warning ".env not found. Copy .env.example to .env and fill in your credentials."
}

# --- Helper: open a new coloured PowerShell window -------------
function Start-ServiceWindow {
    param(
        [string]$Title,
        [string]$WorkingDir,
        [string]$Command,
        [string]$Color = "DarkBlue"
    )
    $escaped = $Command -replace '"', '\"'
    Start-Process powershell -ArgumentList `
        "-NoExit", `
        "-Command", `
        "`$host.UI.RawUI.WindowTitle = '$Title'; `$host.UI.RawUI.BackgroundColor = '$Color'; Clear-Host; Set-Location '$WorkingDir'; $escaped" `
        -WindowStyle Normal
}

Write-Host ""
Write-Host "+----------------------------------------------+" -ForegroundColor Cyan
Write-Host "|     AI Voice Calling Agent - Launcher        |" -ForegroundColor Cyan
Write-Host "+----------------------------------------------+" -ForegroundColor Cyan
Write-Host ""

# --- 1. STT Server ---------------------------------------------
Write-Host "[1/3] Starting STT Server (Qwen3-ASR-1.7B) on port 8001..." -ForegroundColor Yellow
Start-ServiceWindow `
    -Title "STT Server - Qwen3-ASR-1.7B :8001" `
    -WorkingDir "$Root\services\stt_server" `
    -Command "& '$Root\.venv\Scripts\uvicorn.exe' main:app --host 0.0.0.0 --port 8001 --log-level info" `
    -Color "DarkBlue"

Start-Sleep -Seconds 2

# --- 2. TTS Server ---------------------------------------------
Write-Host "[2/3] Starting TTS Server (CosyVoice3) on port 8002..." -ForegroundColor Yellow
# Add CosyVoice to PYTHONPATH so it's importable
$CosyVoicePath = "$Root\services\tts_server\CosyVoice"
$env:PYTHONPATH = "$CosyVoicePath;$CosyVoicePath\third_party\Matcha-TTS;$env:PYTHONPATH"

Start-ServiceWindow `
    -Title "TTS Server - CosyVoice3 :8002" `
    -WorkingDir "$Root\services\tts_server" `
    -Command "`$env:OPENBLAS_NUM_THREADS = '1'; `$env:PYTHONPATH = '$CosyVoicePath;$CosyVoicePath\third_party\Matcha-TTS;' + `$env:PYTHONPATH; & '$Root\.venv\Scripts\uvicorn.exe' main:app --host 0.0.0.0 --port 8002 --log-level info" `
    -Color "DarkGreen"

Start-Sleep -Seconds 2

# --- 3. Dograh (Docker Compose) --------------------------------
Write-Host "[3/3] Starting Dograh stack via Docker Compose..." -ForegroundColor Yellow

# Inject GROQ_API_KEY into environment so docker-compose picks it up
$groqKey = [System.Environment]::GetEnvironmentVariable("GROQ_API_KEY", "Process")
if (-not $groqKey -or $groqKey -eq "gsk_your_groq_api_key_here") {
    Write-Warning "GROQ_API_KEY is not set or still has the placeholder value."
    Write-Warning "Edit your .env file and set a real Groq API key."
}

Start-ServiceWindow `
    -Title "Dograh - Docker Compose :3010" `
    -WorkingDir "$Root\dograh" `
    -Command "docker compose up" `
    -Color "DarkRed"

Start-Sleep -Seconds 2

# --- 4. Cloudflare Tunnel (port 8080 → public) ---------------
Write-Host "[4/4] Starting Cloudflare Tunnel on port 8080..." -ForegroundColor Yellow
Start-ServiceWindow `
    -Title "Cloudflare Tunnel :8080" `
    -WorkingDir "$Root" `
    -Command "cloudflared tunnel --url http://localhost:8080" `
    -Color "DarkMagenta"

# --- Summary ---------------------------------------------------
Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " Services are starting up. URLs:" -ForegroundColor Cyan
Write-Host ""
Write-Host "   STT Server   ->  http://localhost:8001/health" -ForegroundColor White
Write-Host "   TTS Server   ->  http://localhost:8002/health" -ForegroundColor White
Write-Host "   Dograh UI    ->  http://localhost:3010" -ForegroundColor White
Write-Host "   MinIO        ->  http://localhost:9001" -ForegroundColor White
Write-Host ""
Write-Host " Cloudflare Tunnel:" -ForegroundColor Magenta
Write-Host "   Check the 'Cloudflare Tunnel' window for your public URL." -ForegroundColor Magenta
Write-Host "   Copy it and update PUBLIC_BASE_URL in docker-compose.yaml (dograh-api section)" -ForegroundColor Magenta
Write-Host ""
Write-Host " Model load times (first startup):" -ForegroundColor Gray
Write-Host "   STT (Qwen3-ASR-1.7B):   ~60-120s on CPU, ~15s on GPU" -ForegroundColor Gray
Write-Host "   TTS (CosyVoice3-0.5B):  ~30-60s on CPU,  ~10s on GPU" -ForegroundColor Gray
Write-Host ""
Write-Host " Next step: Open http://localhost:3010 and follow" -ForegroundColor Yellow
Write-Host " the README.md to configure providers & create" -ForegroundColor Yellow
Write-Host " your first agent workflow." -ForegroundColor Yellow
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
