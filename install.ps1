Write-Host "🚀 Welcome to VIBETTER Installer!" -ForegroundColor Cyan

# 1. Download/Update codebase
$InstallDir = "$env:USERPROFILE\.vibetter"
if (Test-Path $InstallDir) {
    Write-Host "Updating existing installation in $InstallDir..."
    Set-Location $InstallDir
    git pull -q
} else {
    Write-Host "Cloning VIBETTER..."
    git clone -q https://github.com/neerajbhargav/vibetter.git $InstallDir
}

# 2. Setup Virtual Environment autonomously
Write-Host "Setting up isolated Python environment..."
Set-Location $InstallDir
python -m venv venv
$PythonBin = "$InstallDir\venv\Scripts\python.exe"
& $PythonBin -m pip install --upgrade pip -q
& $PythonBin -m pip install -r backend\requirements.txt -q

# 3. Environment Config
$ApiKey = Read-Host "`n1️⃣ Please enter your Google Gemini (AI Studio) API Key"

$EnvPath = "$InstallDir\backend\.env"
if (!(Test-Path "$InstallDir\backend")) { New-Item -ItemType Directory -Path "$InstallDir\backend" | Out-Null }
"GEMINI_API_KEY=$ApiKey`nVIBETTER_CODEBASE_PATH=." | Out-File -FilePath $EnvPath -Encoding utf8
Write-Host "✅ Saved to backend\.env securely." -ForegroundColor Green

# 4. Native IDE Integration
Write-Host "`n2️⃣ Which IDE are you using?"
Write-Host "   1) Claude Desktop"
Write-Host "   2) Cursor"
Write-Host "   3) Claude Code (Terminal)"
$IdeChoice = Read-Host "Select [1-3]"

if ($IdeChoice -eq '1') {
    $ConfigPath = "$env:APPDATA\Claude\claude_desktop_config.json"
    if (!(Test-Path (Split-Path $ConfigPath))) { New-Item -ItemType Directory -Path (Split-Path $ConfigPath) | Out-Null }
    
    if (Test-Path $ConfigPath) {
        $JsonData = Get-Content -Raw $ConfigPath | ConvertFrom-Json
    } else {
        $JsonData = @{ mcpServers = @{} }
    }
    
    if (-not $JsonData.psobject.properties.match('mcpServers').Count) {
        $JsonData | Add-Member -MemberType NoteProperty -Name 'mcpServers' -Value @{}
    }
    
    $McpPayload = @{
        command = $PythonBin
        args = @("-u", "$InstallDir\backend\src\server.py")
        env = @{ GEMINI_API_KEY = $ApiKey }
    }
    
    $JsonData.mcpServers.vibetter = $McpPayload
    $JsonData | ConvertTo-Json -Depth 10 | Out-File $ConfigPath -Encoding utf8
    
    Write-Host "🎉 Claude Desktop configured!" -ForegroundColor Green
} elseif ($IdeChoice -eq '2') {
    Write-Host "`nFor Cursor, open Settings -> MCP -> Add Command:"
    Write-Host "Name: vibetter"
    Write-Host "Command: $PythonBin -u `"$InstallDir\backend\src\server.py`""
} elseif ($IdeChoice -eq '3') {
    Write-Host "`nIn your target repository directory, run:"
    Write-Host "claude mcp add vibetter $PythonBin -u `"$InstallDir\backend\src\server.py`" -e GEMINI_API_KEY=$ApiKey"
}

Write-Host "`n🔥 VIBETTER setup is complete! Restart your IDE." -ForegroundColor Magenta
