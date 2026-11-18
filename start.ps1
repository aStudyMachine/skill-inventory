#Requires -Version 7.4
param(
    [ValidateRange(1024, 65535)][int]$ApiPort = 8787,
    [ValidateRange(1024, 65535)][int]$WebPort = 5173,
    [switch]$InitializeAdmin
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Push-Location $root
$server = $null
$web = $null
$providedPassword = $env:INVENTORY_ADMIN_PASSWORD
try {
    Remove-Item Env:INVENTORY_ADMIN_PASSWORD -ErrorAction SilentlyContinue
    if ($ApiPort -eq $WebPort) { throw '前后端端口必须不同' }
    $database = if ($env:INVENTORY_DB) { $env:INVENTORY_DB } else { Join-Path $root 'data/inventory.db' }
    foreach ($port in $ApiPort, $WebPort) {
        $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $port)
        try { $listener.Start() }
        catch { throw "端口 $port 被占用，请停止占用它的进程后重试。" }
        finally { $listener.Stop() }
    }
    & mvn -B -f server/pom.xml -DskipTests package
    if ($LASTEXITCODE) { throw '后端构建失败' }
    if (!(Test-Path -LiteralPath (Join-Path $root 'web/node_modules/vite/bin/vite.js'))) {
        & npm --prefix web ci --no-audit --no-fund
        if ($LASTEXITCODE) { throw '前端依赖安装失败' }
    }
    $logs = Join-Path $root 'data/logs'
    New-Item -ItemType Directory -Force $logs | Out-Null
    $password = $providedPassword
    if (($InitializeAdmin -or !(Test-Path -LiteralPath $database)) -and !$password) {
        $password = Read-Host '为内置 admin 设置密码（至少 10 字符）' -MaskInput
    }
    if ($password -and ($password.Length -lt 10 -or [Text.Encoding]::UTF8.GetByteCount($password) -gt 72)) {
        throw '密码至少 10 个字符，且 UTF-8 编码不超过 72 字节'
    }
    $server = Start-Process java -ArgumentList '-jar', 'server/target/skill-inventory-0.2.0.jar' `
        -WorkingDirectory $root -WindowStyle Hidden -PassThru `
        -Environment @{INVENTORY_ADMIN_PASSWORD=$password; SERVER_PORT="$ApiPort"} `
        -RedirectStandardOutput (Join-Path $logs 'server.log') -RedirectStandardError (Join-Path $logs 'server-error.log')
    $password = $null
    $web = Start-Process node -ArgumentList 'node_modules/vite/bin/vite.js', '--strictPort', '--port', "$WebPort" `
        -WorkingDirectory (Join-Path $root 'web') -WindowStyle Hidden -PassThru `
        -Environment @{INVENTORY_API_PORT="$ApiPort"} `
        -RedirectStandardOutput (Join-Path $logs 'web.log') -RedirectStandardError (Join-Path $logs 'web-error.log')
    $deadline = [DateTime]::UtcNow.AddSeconds(40)
    do {
        if ($server.HasExited -or $web.HasExited) { throw "服务启动失败，日志位于 $logs" }
        $ready = $false
        try {
            $api = Invoke-WebRequest "http://127.0.0.1:$ApiPort/api/v1/session" -TimeoutSec 1 -SkipHttpErrorCheck
            $ui = Invoke-WebRequest "http://127.0.0.1:$WebPort" -TimeoutSec 1
            $ready = ($api.StatusCode -eq 401 -and $ui.StatusCode -eq 200)
        } catch {
            Start-Sleep -Milliseconds 300
        }
    } until ($ready -or [DateTime]::UtcNow -ge $deadline)
    if (!$ready) { throw "等待服务就绪超时，日志位于 $logs" }
    Write-Host "网页 http://127.0.0.1:$WebPort"
    Write-Host "接口 http://127.0.0.1:$ApiPort/api/v1"
    Write-Host '按 Ctrl+C 停止前后端。'
    while (!$server.HasExited -and !$web.HasExited) { Start-Sleep -Seconds 1 }
    throw "服务已退出，日志位于 $logs"
} finally {
    foreach ($process in $web, $server) {
        if ($null -ne $process -and !$process.HasExited) {
            $process.Kill($true)
            $process.WaitForExit()
        }
    }
    if ($providedPassword) { $env:INVENTORY_ADMIN_PASSWORD = $providedPassword }
    Pop-Location
}
