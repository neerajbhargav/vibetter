#Requires -Version 5.1
$ErrorActionPreference = 'Stop'

function Write-Info    { param($m) Write-Host $m -ForegroundColor Cyan }
function Write-Success { param($m) Write-Host "✅ $m" -ForegroundColor Green }
function Write-Warn    { param($m) Write-Host "⚠️  $m" -ForegroundColor Yellow }
function Write-Err     { param($m) Write-Host "❌ $m" -ForegroundColor Red }

Write-Host ""
Write-Host "╔══════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║        VIBETTER — One-Line Install       ║" -ForegroundColor Cyan
Write-Host "║   Cognitive Codebase Bridge for Gemini   ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ─── 1. Install / Update ───────────────────────────────────────────────────────
$InstallDir = "$env:USERPROFILE\.vibetter"

if (Test-Path "$InstallDir\.git") {
    Write-Info "Updating existing installation..."
    # Preserve .env, fetch remote, force-reset to origin/main (no merge = no conflicts)
    $EnvBackup = $null
    if (Test-Path "$InstallDir\backend\.env") {
        $EnvBackup = Get-Content "$InstallDir\backend\.env" -Raw
    }
    git -C $InstallDir fetch origin -q 2>$null
    git -C $InstallDir reset --hard origin/main 2>$null
    if ($EnvBackup) {
        [System.IO.File]::WriteAllText("$InstallDir\backend\.env", $EnvBackup)
    }
    # Re-exec the freshly updated script from disk so any installer fixes take effect.
    # When run via iex the old in-memory copy would otherwise keep running.
    $LocalScript = "$InstallDir\install.ps1"
    if (Test-Path $LocalScript) {
        & $LocalScript
        exit
    }
} else {
    Write-Info "Installing VIBETTER to ~/.vibetter..."
    git clone -q https://github.com/neerajbhargav/vibetter.git $InstallDir
}

# ─── 2. Python venv ────────────────────────────────────────────────────────────
Write-Info "Setting up Python environment..."

$PythonCmd = $null
foreach ($cmd in @('python', 'python3', 'py')) {
    try {
        $ver = & $cmd -c "import sys; print(sys.version_info >= (3,9))" 2>$null
        if ($ver -eq 'True') { $PythonCmd = $cmd; break }
    } catch {}
}

if (-not $PythonCmd) {
    Write-Err "Python 3.9+ is required. Install from https://python.org and re-run."
    exit 1
}

$PythonBin = "$InstallDir\venv\Scripts\python.exe"

if (-not (Test-Path $PythonBin)) {
    & $PythonCmd -m venv "$InstallDir\venv"
}

& $PythonBin -m pip install --upgrade pip -q
& $PythonBin -m pip install -r "$InstallDir\backend\requirements.txt" -q
Write-Success "Python environment ready"

# ─── 3. Gemini API Key ─────────────────────────────────────────────────────────
Write-Host ""
Write-Info "Get a free Gemini API key at: https://aistudio.google.com/apikey"
Write-Host ""
$ApiKey = Read-Host "Enter your Gemini API Key"

if ([string]::IsNullOrWhiteSpace($ApiKey)) {
    Write-Err "API key cannot be empty."
    exit 1
}

# Verify the key
Write-Info "Verifying API key..."
$Verify = & $PythonBin -c @"
try:
    from google import genai
    c = genai.Client(api_key='$ApiKey')
    r = c.models.generate_content(model='gemini-2.0-flash', contents='Say: OK')
    print('OK')
except Exception as e:
    print(f'FAIL:{e}')
"@ 2>$null

if ($Verify -eq 'OK') {
    Write-Success "API key verified!"
} else {
    Write-Warn "Could not verify key right now (may be a quota issue). Proceeding anyway."
    Write-Warn "If tools fail, get a fresh key at: https://aistudio.google.com/apikey"
}

if (-not (Test-Path "$InstallDir\backend")) { New-Item -ItemType Directory -Path "$InstallDir\backend" | Out-Null }
"GEMINI_API_KEY=$ApiKey" | Out-File -FilePath "$InstallDir\backend\.env" -Encoding utf8

# ─── 4. Auto-detect and register IDEs ─────────────────────────────────────────
Write-Host ""
Write-Info "Detecting installed IDEs..."
$Registered = $false

function Register-McpJson {
    param([string]$ConfigPath, [string]$IdeName)
    $dir = Split-Path $ConfigPath
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

    $data = @{}
    if (Test-Path $ConfigPath) {
        try { $data = (Get-Content -Raw $ConfigPath | ConvertFrom-Json -AsHashtable) } catch {}
    }

    if (-not $data.ContainsKey('mcpServers')) { $data['mcpServers'] = @{} }

    # Normalize to hashtable
    $servers = @{}
    if ($data['mcpServers'] -ne $null) {
        if ($data['mcpServers'] -is [hashtable]) {
            $servers = $data['mcpServers']
        } else {
            $data['mcpServers'].PSObject.Properties | ForEach-Object { $servers[$_.Name] = $_.Value }
        }
    }

    $servers['vibetter'] = [ordered]@{
        command = $PythonBin
        args    = @('-u', "$InstallDir\backend\src\server.py")
        env     = @{ GEMINI_API_KEY = $ApiKey }
    }
    $data['mcpServers'] = $servers

    $data | ConvertTo-Json -Depth 10 | Out-File $ConfigPath -Encoding utf8
    Write-Success "$IdeName configured!"
}

# Claude Code (auto-register via CLI)
if (Get-Command claude -ErrorAction SilentlyContinue) {
    try {
        claude mcp remove vibetter -s user 2>$null
        claude mcp add vibetter -s user `
            -e "GEMINI_API_KEY=$ApiKey" `
            -- $PythonBin -u "$InstallDir\backend\src\server.py" 2>$null
        Write-Success "Claude Code — auto-registered (no restart needed)"
        $Registered = $true
    } catch {
        Write-Warn "Claude Code detected but auto-registration failed."
        Write-Warn "Run manually: claude mcp add vibetter -s user -e GEMINI_API_KEY=$ApiKey -- `"$PythonBin`" -u `"$InstallDir\backend\src\server.py`""
    }
}

# Cursor
if (Test-Path "$env:USERPROFILE\.cursor") {
    Register-McpJson "$env:USERPROFILE\.cursor\mcp.json" "Cursor"
    $Registered = $true
}

# Claude Desktop (Windows)
if (Test-Path "$env:APPDATA\Claude") {
    Register-McpJson "$env:APPDATA\Claude\claude_desktop_config.json" "Claude Desktop"
    $Registered = $true
}

# Windsurf
if (Test-Path "$env:USERPROFILE\.codeium\windsurf") {
    Register-McpJson "$env:USERPROFILE\.codeium\windsurf\mcp_config.json" "Windsurf"
    $Registered = $true
}

# VS Code (Roo/Cline)
if (Get-Command code -ErrorAction SilentlyContinue) {
    Register-McpJson "$env:USERPROFILE\.vscode\mcp.json" "VS Code (Roo/Cline)"
    $Registered = $true
}

if (-not $Registered) {
    Write-Host ""
    Write-Warn "No supported IDE auto-detected. Add VIBETTER manually:"
    Write-Host ""
    Write-Host "  Claude Code:  claude mcp add vibetter -s user -e GEMINI_API_KEY=$ApiKey -- `"$PythonBin`" -u `"$InstallDir\backend\src\server.py`"" -ForegroundColor White
    Write-Host ""
    Write-Host '  Any IDE with mcp.json support:' -ForegroundColor White
    Write-Host "  { `"mcpServers`": { `"vibetter`": { `"command`": `"$PythonBin`", `"args`": [`"-u`", `"$InstallDir\backend\src\server.py`"], `"env`": { `"GEMINI_API_KEY`": `"$ApiKey`" } } } }" -ForegroundColor Gray
}

# ─── 5. Done ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "╔══════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║         VIBETTER is ready to use!        ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Host "  Open any project in your IDE and use these tools:" -ForegroundColor White
Write-Host ""
Write-Host "  explain_last_change()        — understand what AI just generated" -ForegroundColor Cyan
Write-Host "  scholar_explain(file, q)     — explain any file or function" -ForegroundColor Cyan
Write-Host "  debug_error_in_context(err)  — paste an error, get a fix" -ForegroundColor Cyan
Write-Host "  generate_blueprint()         — visualize your codebase map" -ForegroundColor Cyan
Write-Host "  generate_audio_overview(q)   — listen to a code walkthrough" -ForegroundColor Cyan
Write-Host ""
