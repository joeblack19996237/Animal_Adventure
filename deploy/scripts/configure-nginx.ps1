param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot
)

$ErrorActionPreference = "Stop"

$resolvedRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$normalizedRoot = $resolvedRoot.Replace('\', '/').TrimEnd('/')

$templatePath = Join-Path $resolvedRoot "deploy\nginx\animal-adventure.nginx.conf.template"
$outputPath = Join-Path $resolvedRoot "deploy\nginx\animal-adventure.nginx.conf"

if (-not (Test-Path $templatePath)) {
    Write-Error "Template not found: $templatePath"
    exit 1
}

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$content = [System.IO.File]::ReadAllText($templatePath, $utf8NoBom)
$generated = $content.Replace("{{PROJECT_ROOT}}", $normalizedRoot)
[System.IO.File]::WriteAllText($outputPath, $generated, $utf8NoBom)

Write-Host "Generated: $outputPath"
