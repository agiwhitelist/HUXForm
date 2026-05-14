# HUXForm — one-command bootstrap (Windows / PowerShell 7+).
#
#   .\bin\huxform.ps1              # interactive: setup if needed, then start
#   .\bin\huxform.ps1 setup        # only run setup
#   .\bin\huxform.ps1 start        # start dev (api + web)
#   .\bin\huxform.ps1 doctor       # check deps + API key
#   .\bin\huxform.ps1 clean        # remove .venv, node_modules, data

param([string]$Cmd = "start")

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..").Path
$Api  = Join-Path $Root "apps\api"
$Web  = Join-Path $Root "apps\web"
$EnvFile = Join-Path $Root ".env"
$SIGIL = "$([char]0x25C7)"

function Write-Dim   ([string]$t) { Write-Host $t -ForegroundColor DarkGray -NoNewline }
function Write-Ink   ([string]$t) { Write-Host $t -ForegroundColor White    -NoNewline }
function Write-Sig   ([string]$t) { Write-Host $t -ForegroundColor Red      -NoNewline }
function Write-Good  ([string]$t) { Write-Host $t -ForegroundColor Green    -NoNewline }
function Write-Bad   ([string]$t) { Write-Host $t -ForegroundColor Red      -NoNewline }

function Banner {
    Write-Host ""
    Write-Sig $SIGIL; Write-Host " " -NoNewline; Write-Ink "HUXForm"
    Write-Dim "  — the interface takes the shape of the task"; Write-Host ""
    Write-Dim "  ────────────────────────────────────────────────────"; Write-Host ""
    Write-Host ""
}

function Has-Cmd([string]$name) {
    $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

function Require-Cmd([string]$name, [string]$min) {
    if (Has-Cmd $name) {
        Write-Good "  ✓"; Write-Host "  $name  $((Get-Command $name).Source)"
        return $true
    }
    Write-Bad "  ✗"; Write-Host "  missing: $name (need $min or newer)"
    return $false
}

function Has-Key {
    if (-not (Test-Path $EnvFile)) { return $false }
    $c = Get-Content $EnvFile -Raw
    return ($c -match "AGUI_LLM_API_KEY=(?!your_)\S{8,}")
}

function Doctor {
    Banner
    Write-Dim "  preflight"; Write-Host ""; Write-Host ""
    $py = $false
    if (Has-Cmd "python3") { $py = Require-Cmd "python3" "3.11" }
    elseif (Has-Cmd "python") { $py = Require-Cmd "python" "3.11" }
    else { Write-Bad "  ✗"; Write-Host "  missing: python (need 3.11+)" }
    Require-Cmd "node" "20" | Out-Null
    Require-Cmd "npm" "10" | Out-Null
    Write-Host ""
    if (Has-Key) {
        Write-Good "  ✓"; Write-Host "  .env has an API key"
    } else {
        Write-Bad "  ✗"; Write-Host "  .env is missing or has no API key (run: .\bin\huxform.ps1 setup)"
    }
    Write-Host ""
}

function Resolve-Python {
    if (Has-Cmd "python3") { return "python3" }
    if (Has-Cmd "python")  { return "python" }
    throw "python not found — install Python 3.11+ first"
}

function Prompt-Env {
    if (Has-Key) { return }
    Write-Host ""
    Write-Dim "  HUXForm talks to any provider that speaks the Anthropic Messages or"
    Write-Host ""
    Write-Dim "  OpenAI Chat Completions API. Default: Anthropic Claude Opus 4.7."
    Write-Host ""; Write-Host ""
    Write-Host "  paste your " -NoNewline
    Write-Ink "Anthropic API key"
    Write-Host "  ⟶  " -NoNewline
    $key = Read-Host
    if ([string]::IsNullOrWhiteSpace($key)) {
        Write-Bad "  no key — aborting."; Write-Host ""
        exit 1
    }
    @"
# HUXForm — LLM provider
AGUI_LLM_PROTOCOL=anthropic
AGUI_LLM_BASE_URL=https://api.anthropic.com
AGUI_LLM_MODEL=claude-opus-4-7
AGUI_LLM_API_KEY=$key
AGUI_LLM_MAX_TOKENS=4096
AGUI_LLM_TEMPERATURE=0.6
AGUI_DATA_DIR=.huxform-data
"@ | Set-Content -Path $EnvFile -Encoding UTF8
    Write-Good "  ✓"; Write-Host "  wrote .env"
}

function Setup {
    Banner
    Write-Dim "  setup"; Write-Host ""; Write-Host ""
    Prompt-Env
    Write-Host ""
    $py = Resolve-Python
    Write-Dim "  api · creating Python venv"; Write-Host ""
    Push-Location $Api
    try {
        & $py -m venv .venv | Out-Null
        Write-Dim "  api · installing dependencies"; Write-Host ""
        $venvPy = Join-Path $Api ".venv\Scripts\python.exe"
        & $venvPy -m pip install --upgrade pip -q | Out-Null
        & $venvPy -m pip install -e . -q | Out-Null
    } finally {
        Pop-Location
    }
    Write-Dim "  web · installing dependencies"; Write-Host ""
    Push-Location $Web
    try {
        npm install --silent | Out-Null
    } finally {
        Pop-Location
    }
    Write-Host ""
    Write-Good "  ✓"; Write-Host "  setup complete."
    Write-Host ""
    Write-Dim "  next:  .\bin\huxform.ps1 start"; Write-Host ""
}

function Start-Dev {
    Banner
    if (-not (Test-Path "$Api\.venv") -or -not (Test-Path "$Web\node_modules") -or -not (Test-Path $EnvFile)) {
        Write-Dim "  first-run detected — running setup."; Write-Host ""
        Setup
        Write-Host ""
    }
    Write-Dim "  starting api on :8001 · web on :5173"; Write-Host ""
    Write-Dim "  open  http://localhost:5173"; Write-Host ""; Write-Host ""

    $apiLog = Join-Path $Root ".huxform-api.log"
    $webLog = Join-Path $Root ".huxform-web.log"
    $uvicorn = Join-Path $Api ".venv\Scripts\uvicorn.exe"

    # Copy env into api dir (avoids spaces-in-path issue with --env-file)
    Copy-Item $EnvFile (Join-Path $Api ".env") -Force

    $api = Start-Process -PassThru -FilePath $uvicorn `
        -ArgumentList @("src.main:app","--host","127.0.0.1","--port","8001","--env-file",".env") `
        -WorkingDirectory $Api -WindowStyle Hidden `
        -RedirectStandardOutput $apiLog -RedirectStandardError "$apiLog.err"

    for ($i = 0; $i -lt 40; $i++) {
        try {
            if ((Invoke-WebRequest -Uri "http://127.0.0.1:8001/health" -UseBasicParsing -TimeoutSec 1).StatusCode -eq 200) {
                Write-Good "  ✓"; Write-Host "  api ready (pid $($api.Id))"; break
            }
        } catch { Start-Sleep -Milliseconds 500 }
    }

    $web = Start-Process -PassThru -FilePath "npm" -ArgumentList @("run","dev") `
        -WorkingDirectory $Web -WindowStyle Hidden `
        -RedirectStandardOutput $webLog -RedirectStandardError "$webLog.err"

    for ($i = 0; $i -lt 40; $i++) {
        try {
            if ((Invoke-WebRequest -Uri "http://127.0.0.1:5173" -UseBasicParsing -TimeoutSec 1).StatusCode -eq 200) {
                Write-Good "  ✓"; Write-Host "  web ready (pid $($web.Id))"; break
            }
        } catch { Start-Sleep -Milliseconds 500 }
    }

    Write-Host ""
    Write-Ink "  → http://localhost:5173"; Write-Host ""
    Write-Host ""
    Write-Dim "  logs: .huxform-api.log · .huxform-web.log"; Write-Host ""
    Write-Dim "  press Ctrl+C to stop both"; Write-Host ""

    Start-Process "http://localhost:5173"

    try {
        Wait-Process -Id $api.Id, $web.Id
    } finally {
        if (-not $api.HasExited) { Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue }
        if (-not $web.HasExited) { Stop-Process -Id $web.Id -Force -ErrorAction SilentlyContinue }
    }
}

function Clean {
    Banner
    Write-Dim "  removing .venv, node_modules, data"; Write-Host ""
    Remove-Item -Recurse -Force "$Api\.venv","$Web\node_modules","$Root\.huxform-data","$Root\.huxform-api.log","$Root\.huxform-web.log" -ErrorAction SilentlyContinue
    Write-Good "  ✓"; Write-Host "  clean."
}

switch ($Cmd) {
    "setup"  { Setup }
    "start"  { Start-Dev }
    "doctor" { Doctor }
    "clean"  { Clean }
    default {
        Banner
        Write-Ink "  usage:"; Write-Host ""
        Write-Host "    .\bin\huxform.ps1              start (run setup first if needed)"
        Write-Host "    .\bin\huxform.ps1 setup        install dependencies, write .env"
        Write-Host "    .\bin\huxform.ps1 doctor       check prerequisites"
        Write-Host "    .\bin\huxform.ps1 clean        remove .venv, node_modules, data"
        Write-Host ""
    }
}
