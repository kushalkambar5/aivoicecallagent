#!/usr/bin/env pwsh
# ============================================================
# setup_cosyvoice.ps1
# Clones the official CosyVoice repo and installs its
# dependencies into the current Python environment.
#
# Run this ONCE before starting the TTS server.
# ============================================================

$ErrorActionPreference = "Stop"
$TtsDir = "$PSScriptRoot\services\tts_server"
$CosyVoiceDir = "$TtsDir\CosyVoice"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " CosyVoice3 Setup Script" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Clone CosyVoice repo if not already present
if (-not (Test-Path $CosyVoiceDir)) {
    Write-Host "[1/4] Cloning FunAudioLLM/CosyVoice repository..." -ForegroundColor Yellow
    git clone --depth 1 https://github.com/FunAudioLLM/CosyVoice.git $CosyVoiceDir
    Write-Host "      [+] Cloned to $CosyVoiceDir" -ForegroundColor Green
} else {
    Write-Host "[1/4] CosyVoice repo already exists at $CosyVoiceDir - skipping clone." -ForegroundColor Gray
}

# 2. Install CosyVoice requirements
Write-Host ""
Write-Host "[2/4] Installing CosyVoice dependencies..." -ForegroundColor Yellow
Push-Location $CosyVoiceDir
try {
    # Install third-party deps first (pynini, WeTextProcessing need special handling on Windows)
    pip install -r requirements.txt --no-warn-script-location
    Write-Host "      [+] CosyVoice requirements installed." -ForegroundColor Green
} finally {
    Pop-Location
}

# 3. Install TTS server requirements
Write-Host ""
Write-Host "[3/4] Installing TTS server requirements..." -ForegroundColor Yellow
pip install -r "$TtsDir\requirements.txt" --no-warn-script-location
Write-Host "      [+] TTS server requirements installed." -ForegroundColor Green

# 4. Install STT server requirements
Write-Host ""
Write-Host "[4/4] Installing STT server requirements..." -ForegroundColor Yellow
pip install -r "$PSScriptRoot\services\stt_server\requirements.txt" --no-warn-script-location
Write-Host "      [+] STT server requirements installed." -ForegroundColor Green

Write-Host ""
Write-Host "==================================================" -ForegroundColor Green
Write-Host " Setup complete! You can now run start_services.ps1" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
