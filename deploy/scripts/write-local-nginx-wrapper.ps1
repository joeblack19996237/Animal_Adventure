param(
    [string]$ProjectRoot = "D:\Animal_Adventure",
    [string]$NginxRoot = "D:\nginx"
)

$ErrorActionPreference = "Stop"

$resolvedProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$resolvedNginxRoot = [System.IO.Path]::GetFullPath($NginxRoot)
$projectRootSlash = $resolvedProjectRoot.Replace('\', '/').TrimEnd('/')
$nginxRootSlash = $resolvedNginxRoot.Replace('\', '/').TrimEnd('/')

$tmpDir = Join-Path $resolvedProjectRoot ".tmp"
$tempDir = Join-Path $tmpDir "temp"
New-Item -ItemType Directory -Force $tmpDir, $tempDir | Out-Null

$wrapperPath = Join-Path $tmpDir "nginx-animal-adventure-wrapper.conf"
$content = @"
error_log $projectRootSlash/.tmp/nginx-error.log;
pid $projectRootSlash/.tmp/nginx.pid;

events {
    worker_connections 1024;
}

http {
    include $nginxRootSlash/conf/mime.types;
    default_type application/octet-stream;
    access_log $projectRootSlash/.tmp/nginx-access.log;

    client_body_temp_path $projectRootSlash/.tmp/temp/client_body_temp;
    proxy_temp_path $projectRootSlash/.tmp/temp/proxy_temp;
    fastcgi_temp_path $projectRootSlash/.tmp/temp/fastcgi_temp;
    uwsgi_temp_path $projectRootSlash/.tmp/temp/uwsgi_temp;
    scgi_temp_path $projectRootSlash/.tmp/temp/scgi_temp;

    sendfile on;
    keepalive_timeout 65;

    include $projectRootSlash/deploy/nginx/animal-adventure.nginx.conf;
}
"@

[System.IO.File]::WriteAllText($wrapperPath, $content, [System.Text.Encoding]::ASCII)
Write-Host "Generated: $wrapperPath"
