param(
    [ValidateSet("chromium", "webkit-ipad", "all")]
    [string]$Project = "chromium",
    [switch]$Full,
    [string]$ProjectRoot = "D:\Animal_Adventure",
    [string]$PythonPath = "C:\Users\OEM\AppData\Local\Python\bin\python.exe",
    [string]$NpmPath = "C:\Program Files\nodejs\npm.CMD",
    [string]$NginxPath = "D:\nginx\nginx.exe",
    [string]$DatabasePath = "D:\Animal_Adventure\.tmp\final-acceptance.sqlite3"
)

$ErrorActionPreference = "Stop"

$resolvedRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$resolvedDatabase = [System.IO.Path]::GetFullPath($DatabasePath)
$tmpDir = Join-Path $resolvedRoot ".tmp"
New-Item -ItemType Directory -Force $tmpDir | Out-Null
Remove-Item (Join-Path $tmpDir "nginx-access.log") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $tmpDir "nginx-error.log") -Force -ErrorAction SilentlyContinue

function Wait-HttpOk {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest $Url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -eq 200) {
                return
            }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    } while ((Get-Date) -lt $deadline)

    throw "Timed out waiting for $Url"
}

function Assert-HttpOk {
    param(
        [string]$Url,
        [string]$Method = "Get"
    )

    $response = Invoke-WebRequest $Url -UseBasicParsing -TimeoutSec 15 -Method $Method
    if ($response.StatusCode -ne 200) {
        throw "$Url returned $($response.StatusCode)"
    }
    Write-Host "OK $($response.StatusCode) $Url"
}

$initScriptPath = Join-Path $tmpDir "init-final-acceptance-db.py"
$initScript = @"
import sys
from pathlib import Path
sys.path.insert(0, r"$resolvedRoot")
from app.db import init_db
init_db(Path(r"$resolvedDatabase"))
"@
[System.IO.File]::WriteAllText($initScriptPath, $initScript, [System.Text.Encoding]::ASCII)

& $PythonPath $initScriptPath
if ($LASTEXITCODE -ne 0) {
    throw "Database initialization failed with exit code $LASTEXITCODE"
}

& powershell -ExecutionPolicy Bypass -File (Join-Path $resolvedRoot "deploy\scripts\configure-nginx.ps1") -ProjectRoot $resolvedRoot
& powershell -ExecutionPolicy Bypass -File (Join-Path $resolvedRoot "deploy\scripts\write-local-nginx-wrapper.ps1") -ProjectRoot $resolvedRoot -NginxRoot ([System.IO.Path]::GetDirectoryName($NginxPath))

$nginxConfig = Join-Path $tmpDir "nginx-animal-adventure-wrapper.conf"
& $NginxPath -t -p "$tmpDir\" -c $nginxConfig
if ($LASTEXITCODE -ne 0) {
    throw "Nginx config test failed with exit code $LASTEXITCODE"
}

$apiJob = $null
$nginxJob = $null

try {
    $apiJob = Start-Job -ScriptBlock {
        param($Root, $Python, $Db)
        Set-Location $Root
        $env:DATABASE_PATH = $Db
        & $Python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
    } -ArgumentList $resolvedRoot, $PythonPath, $resolvedDatabase

    Wait-HttpOk "http://127.0.0.1:8000/health" 45
    Wait-HttpOk "http://127.0.0.1:8000/ready" 45

    $nginxJob = Start-Job -ScriptBlock {
        param($Root, $Nginx, $Config)
        Set-Location $Root
        & $Nginx -p "$Root\.tmp\" -c $Config -g "daemon off;"
    } -ArgumentList $resolvedRoot, $NginxPath, $nginxConfig

    Wait-HttpOk "http://localhost:8080/" 45
    Assert-HttpOk "http://localhost:8080/"
    $indexResponse = Invoke-WebRequest "http://localhost:8080/" -UseBasicParsing -TimeoutSec 15
    if ($indexResponse.Content -notmatch '["'']/(assets/[^"'']+\.(js|css))["'']') {
        throw "Could not find built frontend asset reference in Nginx-served index.html"
    }
    Assert-HttpOk "http://localhost:8080/$($Matches[1])" "Head"
    Assert-HttpOk "http://localhost:8080/health"
    Assert-HttpOk "http://localhost:8080/ready"
    Assert-HttpOk "http://localhost:8080/assets/images/MapTiles/map_tile_0_0.png" "Head"
    Assert-HttpOk "http://localhost:8080/assets/images/Items/game_map_full.png" "Head"

    $playwrightArgs = @("run", "test:e2e:nginx", "--")
    if (-not $Full) {
        $playwrightArgs += @("--grep", "@phase16-smoke")
    }
    if ($Project -ne "all") {
        $playwrightArgs += @("--project=$Project")
    }
    $playwrightArgs += @("--reporter=line", "--workers=1")

    Write-Host "Running: $NpmPath $($playwrightArgs -join ' ')"
    & $NpmPath @playwrightArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Playwright final acceptance failed with exit code $LASTEXITCODE"
    }
} finally {
    if ($nginxJob -ne $null) {
        Stop-Job $nginxJob -ErrorAction SilentlyContinue
        Receive-Job $nginxJob -ErrorAction SilentlyContinue | Out-Host
        Remove-Job $nginxJob -Force -ErrorAction SilentlyContinue
    }
    if ($apiJob -ne $null) {
        Stop-Job $apiJob -ErrorAction SilentlyContinue
        Receive-Job $apiJob -ErrorAction SilentlyContinue | Out-Host
        Remove-Job $apiJob -Force -ErrorAction SilentlyContinue
    }
}
