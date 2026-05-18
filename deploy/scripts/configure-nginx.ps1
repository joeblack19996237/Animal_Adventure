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

$content = [System.IO.File]::ReadAllText($templatePath, [System.Text.Encoding]::UTF8)
$generated = $content.Replace("{{PROJECT_ROOT}}", $normalizedRoot)
[System.IO.File]::WriteAllText($outputPath, $generated, [System.Text.Encoding]::UTF8)

Write-Host "Generated: $outputPath"
