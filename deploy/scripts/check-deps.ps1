# Dependency checker for Animal Adventure MVP (Windows 10)
param()

$ErrorActionPreference = "Continue"
$allFound = $true

function Test-CliTool {
    param([string]$Name, [string]$Cmd)
    $found = Get-Command $Cmd -ErrorAction SilentlyContinue
    if ($found) {
        Write-Host "[OK     ] ${Name}: $($found.Source)"
    } else {
        Write-Host "[MISSING] ${Name}: not found in PATH"
        $script:allFound = $false
    }
}

function Test-PythonModule {
    param([string]$Module)
    python -c "import $Module" 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK     ] ${Module}: module available"
    } else {
        Write-Host "[MISSING] ${Module}: module not available"
        $script:allFound = $false
    }
}

function Test-PlaywrightBrowser {
    param([string]$Browser)
    $script = @"
from playwright.sync_api import sync_playwright
from pathlib import Path
try:
    with sync_playwright() as pw:
        bt = getattr(pw, '$Browser')
        print('OK' if Path(bt.executable_path).exists() else 'MISSING')
except Exception:
    print('MISSING')
"@
    $result = $script | python 2>&1
    if ($result -match "^OK") {
        Write-Host "[OK     ] playwright-${Browser}: installed"
    } else {
        Write-Host "[MISSING] playwright-${Browser}: not installed"
        $script:allFound = $false
    }
}

Test-CliTool  "python"  "python"
Test-CliTool  "node"    "node"
Test-CliTool  "npm"     "npm"
Test-CliTool  "nginx"   "nginx"
Test-PythonModule "sqlite3"
Test-PlaywrightBrowser "chromium"
Test-PlaywrightBrowser "webkit"

Write-Host ""
if ($allFound) {
    Write-Host "All dependencies found."
    exit 0
} else {
    Write-Host "One or more dependencies are missing. Install them before running Animal Adventure."
    exit 1
}
