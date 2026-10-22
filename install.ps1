#Requires -Version 5.1
# VIBETTER installer for Windows.
#
#   iwr -useb https://raw.githubusercontent.com/neerajbhargav/vibetter/main/install.ps1 | iex
#
# Non-interactive use: set VIBETTER_PROVIDER (gemini, openai, anthropic or ollama) and, for a
# cloud provider, its key variable (GEMINI_API_KEY, OPENAI_API_KEY or ANTHROPIC_API_KEY).
# The key is stored once, in ~\.vibetter\.env. IDE configs only get the command.
# VIBETTER_REPO and VIBETTER_REF pick another clone source or branch (used for testing).
$ErrorActionPreference = 'Stop'

function Write-Info    { param($m) Write-Host $m -ForegroundColor Cyan }
function Write-Success { param($m) Write-Host "[OK] $m" -ForegroundColor Green }
function Write-Warn    { param($m) Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Write-Err     { param($m) Write-Host "[ERR] $m" -ForegroundColor Red }

# Windows PowerShell 5.1 turns native stderr into terminating errors under 'Stop'.
function Invoke-Native {
    param([scriptblock]$Block)
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Block } finally { $ErrorActionPreference = $old }
}

$Repo = if ($env:VIBETTER_REPO) { $env:VIBETTER_REPO } else { 'https://github.com/neerajbhargav/vibetter.git' }
$Ref = if ($env:VIBETTER_REF) { $env:VIBETTER_REF } else { 'main' }
$InstallDir = if ($env:VIBETTER_HOME) { $env:VIBETTER_HOME } else { Join-Path $env:USERPROFILE '.vibetter' }
$EnvFile = Join-Path $InstallDir '.env'
$PythonBin = Join-Path $InstallDir 'venv\Scripts\python.exe'
$VibetterExe = Join-Path $InstallDir 'venv\Scripts\vibetter.exe'

Write-Host ""
Write-Info "VIBETTER installer"
Write-Host ""

# --- 1. Get the code -------------------------------------------------------------
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Write-Err "git is required. Install it and re-run."; exit 1 }
if (Test-Path (Join-Path $InstallDir '.git')) {
    Write-Info "Updating $InstallDir ..."
    Invoke-Native { git -C $InstallDir fetch -q $Repo $Ref 2>$null }
    Invoke-Native { git -C $InstallDir reset -q --hard FETCH_HEAD 2>$null }
    # When run through iex, continue with the script that was just checked out.
    $LocalScript = Join-Path $InstallDir 'install.ps1'
    if ((-not $MyInvocation.MyCommand.Path) -and (Test-Path $LocalScript)) {
        & $LocalScript
        exit
    }
} else {
    Write-Info "Installing to $InstallDir ..."
    Invoke-Native { git clone -q --branch $Ref $Repo $InstallDir 2>$null }
    if ($LASTEXITCODE -ne 0) { Write-Err "git clone failed."; exit 1 }
}
# Installs before v2 kept settings in backend\.env.
$OldEnv = Join-Path $InstallDir 'backend\.env'
if ((Test-Path $OldEnv) -and -not (Test-Path $EnvFile)) { Move-Item $OldEnv $EnvFile }

# --- 2. Python environment -----------------------------------------------------------
$PythonCmd = $null
foreach ($cmd in @('python3.14', 'python3.13', 'python3.12', 'python3.11', 'python3.10', 'python3', 'python', 'py')) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { continue }
    $ok = Invoke-Native { & $cmd -c "import sys; print(sys.version_info >= (3, 10))" 2>$null }
    if ($ok -eq 'True') { $PythonCmd = $cmd; break }
}
if (-not $PythonCmd) { Write-Err "Python 3.10 or newer is required. Install it from https://python.org and re-run."; exit 1 }
if (-not (Test-Path $PythonBin)) { Invoke-Native { & $PythonCmd -m venv (Join-Path $InstallDir 'venv') 2>$null } }

# --- 3. Provider and key ------------------------------------------------------------
$Provider = $env:VIBETTER_PROVIDER
if (-not $Provider) {
    Write-Host "Which AI provider do you want to use?"
    Write-Host "  1) Google Gemini     (key: https://aistudio.google.com/apikey)"
    Write-Host "  2) OpenAI            (key: https://platform.openai.com/api-keys)"
    Write-Host "  3) Anthropic Claude  (key: https://console.anthropic.com/settings/keys)"
    Write-Host "  4) Ollama            (local, no key: https://ollama.com)"
    $Choice = Read-Host "Choose [1-4, default 1]"
    switch ($Choice) {
        { $_ -in @('', '1') } { $Provider = 'gemini' }
        '2' { $Provider = 'openai' }
        '3' { $Provider = 'anthropic' }
        '4' { $Provider = 'ollama' }
        default { Write-Err "Invalid choice."; exit 1 }
    }
}
$KeyVars = @{ gemini = 'GEMINI_API_KEY'; openai = 'OPENAI_API_KEY'; anthropic = 'ANTHROPIC_API_KEY'; ollama = '' }
if (-not $KeyVars.ContainsKey($Provider)) { Write-Err "Unknown provider '$Provider'."; exit 1 }
$KeyVar = $KeyVars[$Provider]

$ApiKey = ''
if ($KeyVar) {
    $ApiKey = [Environment]::GetEnvironmentVariable($KeyVar)
    if (-not $ApiKey) {
        $HasSaved = (Test-Path $EnvFile) -and (Select-String -Path $EnvFile -Pattern "^$KeyVar=" -Quiet)
        $Prompt = if ($HasSaved) { "Enter your $KeyVar (Enter keeps the saved key)" } else { "Enter your $KeyVar" }
        $Secure = Read-Host $Prompt -AsSecureString
        $Bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
        try { $ApiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Bstr) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Bstr) }
        if (-not $ApiKey -and -not $HasSaved) { Write-Err "An API key is required for $Provider."; exit 1 }
    }
}

Write-Info "Installing the vibetter package with the $Provider SDK ..."
Invoke-Native { & $PythonBin -m pip install -q --upgrade pip 2>$null }
Invoke-Native { & $PythonBin -m pip install -q -e "$InstallDir[$Provider]" 2>$null }
if ($LASTEXITCODE -ne 0) { Write-Err "pip install failed. Run it by hand to see the error."; exit 1 }
Write-Success "Package installed: $VibetterExe"

# Write .env: keep other settings, replace the provider and (if given) the key.
$Lines = @()
if (Test-Path $EnvFile) {
    $Drop = if ($ApiKey) { "^(VIBETTER_PROVIDER|$KeyVar)=" } else { '^VIBETTER_PROVIDER=' }
    $Lines = @(Get-Content $EnvFile | Where-Object { $_ -notmatch $Drop })
}
$Lines += "VIBETTER_PROVIDER=$Provider"
if ($ApiKey) { $Lines += "$KeyVar=$ApiKey" }
[System.IO.File]::WriteAllText($EnvFile, (($Lines -join "`n") + "`n"))
Write-Success "Settings saved to $EnvFile"

# The check reads the key from .env itself, so it never appears in a command line.
if (-not $env:VIBETTER_SKIP_VERIFY) {
    Write-Info "Checking the provider with one short request ..."
    $VerifyScript = @'
import asyncio
from vibetter import config, providers
config.load_env()
try:
    asyncio.run(providers.call_llm("Reply with the single word OK."))
    print("OK")
except config.VibetterError as e:
    print(e)
'@
    $Verify = Invoke-Native { & $PythonBin -c $VerifyScript 2>&1 }
    if ("$Verify".Trim() -eq 'OK') { Write-Success "Provider works" }
    else { Write-Warn "Could not verify the provider: $Verify" }
}

# --- 4. Register with IDEs ------------------------------------------------------------
$Registered = $false
$NeedManual = $false
function Register-Json {
    param([string]$ConfigPath, [string]$IdeName)
    $out = Invoke-Native { & $PythonBin -m vibetter.ide $ConfigPath $VibetterExe 2>&1 }
    if ($LASTEXITCODE -eq 0) {
        Write-Success "$IdeName configured"
        $script:Registered = $true
    } else {
        Write-Warn "$IdeName was not changed: $out"
        $script:NeedManual = $true
    }
}

if (Get-Command claude -ErrorAction SilentlyContinue) {
    Invoke-Native { claude mcp remove vibetter -s user 2>$null | Out-Null }
    $cmdArgs = @('mcp', 'add', 'vibetter', '-s', 'user', '--', $VibetterExe)
    Invoke-Native { & claude @cmdArgs 2>$null | Out-Null }
    if ($LASTEXITCODE -eq 0) { Write-Success "Claude Code registered"; $Registered = $true }
    else { Write-Warn "Claude Code found, but 'claude mcp add' failed." }
}
if (Test-Path (Join-Path $env:USERPROFILE '.cursor')) {
    Register-Json (Join-Path $env:USERPROFILE '.cursor\mcp.json') 'Cursor'
}
if (Test-Path (Join-Path $env:APPDATA 'Claude')) {
    Register-Json (Join-Path $env:APPDATA 'Claude\claude_desktop_config.json') 'Claude Desktop'
}
if (Test-Path (Join-Path $env:USERPROFILE '.codeium\windsurf')) {
    Register-Json (Join-Path $env:USERPROFILE '.codeium\windsurf\mcp_config.json') 'Windsurf'
}

if ((-not $Registered) -or $NeedManual) {
    Write-Host ""
    Write-Warn "Add VIBETTER by hand where it was not registered:"
    Write-Host "  Claude Code:  claude mcp add vibetter -s user -- $VibetterExe"
    Write-Host "  JSON config:  {`"mcpServers`": {`"vibetter`": {`"command`": `"$($VibetterExe -replace '\\', '\\')`"}}}"
}

Write-Host ""
Write-Success "VIBETTER is ready (provider: $Provider)."
Write-Host "  Tools: explain_last_change, scholar_explain, debug_error_in_context, search_code,"
Write-Host "         verify_citations, generate_blueprint, generate_audio_overview"
Write-Host "  Terminal: $VibetterExe ask `"How does X work?`""
Write-Host "  If your IDE starts servers outside the project, set VIBETTER_CODEBASE_PATH in its config."
Write-Host ""
