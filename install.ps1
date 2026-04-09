#Requires -Version 5.1
$ErrorActionPreference = 'Stop'

function Write-Info    { param($m) Write-Host $m -ForegroundColor Cyan }
function Write-Success { param($m) Write-Host "[OK] $m" -ForegroundColor Green }
function Write-Warn    { param($m) Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Write-Err     { param($m) Write-Host "[ERR] $m" -ForegroundColor Red }

Write-Host ""
Write-Host "+------------------------------------------+" -ForegroundColor Cyan
Write-Host "|        VIBETTER - One-Line Install       |" -ForegroundColor Cyan
Write-Host "|   Cognitive Codebase Bridge for AI IDEs  |" -ForegroundColor Cyan
Write-Host "+------------------------------------------+" -ForegroundColor Cyan
Write-Host ""

# --- 1. Install / Update -------------------------------------------------------
$InstallDir = "$env:USERPROFILE\.vibetter"

if (Test-Path "$InstallDir\.git") {
    Write-Info "Updating existing installation..."
    $EnvBackup = $null
    if (Test-Path "$InstallDir\backend\.env") {
        $EnvBackup = Get-Content "$InstallDir\backend\.env" -Raw
    }
    git -C $InstallDir fetch origin -q 2>$null
    git -C $InstallDir reset --hard origin/main 2>$null
    if ($EnvBackup) {
        [System.IO.File]::WriteAllText("$InstallDir\backend\.env", $EnvBackup)
    }
    $LocalScript = "$InstallDir\install.ps1"
    if ((-not $MyInvocation.MyCommand.Path) -and (Test-Path $LocalScript)) {
        & $LocalScript
        exit
    }
} else {
    Write-Info "Installing VIBETTER to ~/.vibetter..."
    git clone -q https://github.com/neerajbhargav/vibetter.git $InstallDir
}

# --- 2. Python venv ------------------------------------------------------------
Write-Info "Setting up Python environment..."

$PythonCmd = $null
foreach ($cmd in @('python', 'python3', 'py')) {
    try {
        $cmdPath = (Get-Command $cmd -ErrorAction SilentlyContinue).Source
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

# --- 3. AI Provider Selection --------------------------------------------------
Write-Host ""
Write-Info "Which AI provider do you want to use?"
Write-Host ""
Write-Host "  1) Google Gemini  (free tier: https://aistudio.google.com/apikey)"
Write-Host "  2) OpenAI/ChatGPT (https://platform.openai.com/api-keys)"
Write-Host "  3) Anthropic Claude (https://console.anthropic.com/settings/keys)"
Write-Host "  4) Ollama - local models, no API key (https://ollama.ai)"
Write-Host ""
$Choice = Read-Host "Choose [1-4, default=1]"
if ([string]::IsNullOrWhiteSpace($Choice)) { $Choice = "1" }

switch ($Choice) {
    "1" { $Provider = "gemini";    $KeyVar = "GEMINI_API_KEY";    $KeyUrl = "https://aistudio.google.com/apikey";          $Sdk = "google-genai" }
    "2" { $Provider = "openai";    $KeyVar = "OPENAI_API_KEY";    $KeyUrl = "https://platform.openai.com/api-keys";        $Sdk = "openai" }
    "3" { $Provider = "anthropic"; $KeyVar = "ANTHROPIC_API_KEY"; $KeyUrl = "https://console.anthropic.com/settings/keys"; $Sdk = "anthropic" }
    "4" { $Provider = "ollama";    $KeyVar = "";                  $KeyUrl = "";                                             $Sdk = "ollama" }
    default { Write-Err "Invalid choice."; exit 1 }
}

# Install provider SDK
Write-Info "Installing $Provider SDK..."
& $PythonBin -m pip install $Sdk -q
Write-Success "$Provider SDK installed"

# Collect API key (skip for Ollama)
$ApiKey = ""
if ($KeyVar) {
    Write-Host ""
    Write-Info "Get your API key at: $KeyUrl"
    Write-Host ""
    $ApiKey = Read-Host "Enter your $KeyVar"

    if ([string]::IsNullOrWhiteSpace($ApiKey)) {
        Write-Err "API key cannot be empty."
        exit 1
    }

    # Verify the key
    Write-Info "Verifying API key..."
    $Verify = & $PythonBin -c @"
try:
    if '$Provider' == 'gemini':
        from google import genai
        c = genai.Client(api_key='$ApiKey')
        r = c.models.generate_content(model='gemini-2.0-flash-lite', contents='Say: OK')
    elif '$Provider' == 'openai':
        import openai
        c = openai.OpenAI(api_key='$ApiKey')
        r = c.chat.completions.create(model='gpt-4o-mini', messages=[{'role':'user','content':'Say: OK'}], max_tokens=5)
    elif '$Provider' == 'anthropic':
        import anthropic
        c = anthropic.Anthropic(api_key='$ApiKey')
        r = c.messages.create(model='claude-haiku-4-20250414', max_tokens=5, messages=[{'role':'user','content':'Say: OK'}])
    print('OK')
except Exception as e:
    print(f'FAIL:{e}')
"@ 2>$null

    if ($Verify -eq 'OK') {
        Write-Success "API key verified!"
    } else {
        Write-Warn "Could not verify key right now (may be a quota issue). Proceeding anyway."
        Write-Warn "Details: $Verify"
    }
}

# Write .env
if (-not (Test-Path "$InstallDir\backend")) { New-Item -ItemType Directory -Path "$InstallDir\backend" | Out-Null }
$EnvContent = "VIBETTER_PROVIDER=$Provider"
if ($ApiKey) { $EnvContent += "`n$KeyVar=$ApiKey" }
[System.IO.File]::WriteAllText("$InstallDir\backend\.env", "$EnvContent`n")

# --- 4. Auto-detect and register IDEs -----------------------------------------
Write-Host ""
Write-Info "Detecting installed IDEs..."
$Registered = $false

function Register-McpJson {
    param([string]$ConfigPath, [string]$IdeName)
    $dir = Split-Path $ConfigPath
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

    $data = $null
    if (Test-Path $ConfigPath) {
        try { $data = Get-Content -Raw $ConfigPath | ConvertFrom-Json } catch {}
    }
    if ($null -eq $data) { $data = New-Object PSObject }

    if ($null -eq $data.mcpServers) {
        $data | Add-Member -MemberType NoteProperty -Name "mcpServers" -Value (New-Object PSObject)
    }

    $envBlock = [ordered]@{ VIBETTER_PROVIDER = $Provider }
    if ($KeyVar) { $envBlock[$KeyVar] = $ApiKey }

    $vibetter = [ordered]@{
        command = $PythonBin
        args    = @('-u', "$InstallDir\backend\src\server.py")
        env     = $envBlock
    }

    $data.mcpServers | Add-Member -MemberType NoteProperty -Name "vibetter" -Value $vibetter -Force

    $json = $data | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText($ConfigPath, $json)
    Write-Success "$IdeName configured!"
}

# Claude Code (auto-register via CLI)
if (Get-Command claude -ErrorAction SilentlyContinue) {
    try {
        claude mcp remove vibetter -s user 2>$null
        $envArgs = @('-e', "VIBETTER_PROVIDER=$Provider")
        if ($KeyVar) { $envArgs += @('-e', "$KeyVar=$ApiKey") }
        $cmdArgs = @('mcp', 'add', 'vibetter', '-s', 'user') + $envArgs + @('--', $PythonBin, '-u', "$InstallDir\backend\src\server.py")
        & claude @cmdArgs 2>$null
        Write-Success "Claude Code - auto-registered (no restart needed)"
        $Registered = $true
    } catch {
        Write-Warn "Claude Code detected but auto-registration failed."
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
    Write-Warn "No supported IDE auto-detected. Add VIBETTER manually."
}

# --- 5. Done -------------------------------------------------------------------
Write-Host ""
Write-Host "+------------------------------------------+" -ForegroundColor Green
Write-Host "|         VIBETTER is ready to use!        |" -ForegroundColor Green
Write-Host "|    Provider: $($Provider.PadRight(27))|" -ForegroundColor Green
Write-Host "+------------------------------------------+" -ForegroundColor Green
Write-Host ""
Write-Host "  Open any project in your IDE and use these tools:" -ForegroundColor White
Write-Host ""
Write-Host "  explain_last_change()        - understand what AI just generated" -ForegroundColor Cyan
Write-Host "  scholar_explain(file, q)     - explain any file or function" -ForegroundColor Cyan
Write-Host "  debug_error_in_context(err)  - paste an error, get a fix" -ForegroundColor Cyan
Write-Host "  generate_blueprint()         - visualize your codebase map" -ForegroundColor Cyan
Write-Host "  generate_audio_overview(q)   - listen to a code walkthrough" -ForegroundColor Cyan
Write-Host ""
