param(
    [string]$ProjectRoot = "D:\Animal_Adventure",
    [string]$PythonPath = "C:\Users\OEM\AppData\Local\Python\bin\python.exe",
    [string]$DatabasePath = "D:\Animal_Adventure\.tmp\final-acceptance.sqlite3",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

$resolvedRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$resolvedDatabase = [System.IO.Path]::GetFullPath($DatabasePath)
$tmpDir = Join-Path $resolvedRoot ".tmp"
New-Item -ItemType Directory -Force $tmpDir | Out-Null

$initScriptPath = Join-Path $tmpDir "init-final-acceptance-db.py"
$initScript = @"
import sys
from pathlib import Path
sys.path.insert(0, r"$resolvedRoot")
from app.db import init_db
init_db(Path(r"$resolvedDatabase"))
"@
[System.IO.File]::WriteAllText($initScriptPath, $initScript, [System.Text.Encoding]::ASCII)

$init = Start-Process `
    -FilePath $PythonPath `
    -ArgumentList @($initScriptPath) `
    -WorkingDirectory $resolvedRoot `
    -WindowStyle Hidden `
    -Wait `
    -PassThru

if ($init.ExitCode -ne 0) {
    throw "Database initialization failed with exit code $($init.ExitCode)"
}

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $PythonPath
$psi.Arguments = "-m uvicorn app.main:app --host 127.0.0.1 --port $Port"
$psi.WorkingDirectory = $resolvedRoot
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$env:DATABASE_PATH = $resolvedDatabase

$proc = [System.Diagnostics.Process]::Start($psi)
$pidPath = Join-Path $tmpDir "uvicorn.pid"
[System.IO.File]::WriteAllText($pidPath, [string]$proc.Id, [System.Text.Encoding]::ASCII)
Write-Host "Started FastAPI pid=$($proc.Id) database=$resolvedDatabase"
