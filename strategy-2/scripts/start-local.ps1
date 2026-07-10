$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root

$StrategyName = "Strategy 2"
$FrontendUrl = "http://localhost:3001"
$FrontendPort = 3001
$BackendPort = 8001
$ChromeProfileDir = Join-Path $env:TEMP "indian-algo-all-strategies"
$ChromeDebugPort = 9333

function Stop-PidTree {
    param([Parameter(Mandatory = $true)][int]$ProcId)
    if ($ProcId -le 0) { return }
    # Use cmd so taskkill stderr ("process not found") never becomes a terminating PowerShell error.
    cmd.exe /c "taskkill /PID $ProcId /T /F >nul 2>&1" | Out-Null
}

function Clear-ListenPort {
    param([Parameter(Mandatory = $true)][int]$Port)
    $conns = @()
    try {
        $conns = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    } catch {
        $conns = @()
    }
    $pids = @(
        $conns |
            ForEach-Object { [int]$_.OwningProcess } |
            Where-Object { $_ -gt 0 } |
            Select-Object -Unique
    )
    foreach ($procId in $pids) {
        Write-Host "  Freeing port $Port (PID $procId)..." -ForegroundColor DarkYellow
        Stop-PidTree -ProcId $procId
    }
}

function Start-ManagedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Command
    )
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "cmd.exe"
    $psi.Arguments = "/d /s /c `"$Command`""
    $psi.WorkingDirectory = $root
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $false
    $process = [System.Diagnostics.Process]::Start($psi)
    return [pscustomobject]@{ Name = $Name; Process = $process }
}

function Stop-ProcessTree {
    param($Process)
    if ($null -eq $Process) { return }
    try {
        if (-not $Process.HasExited) {
            Stop-PidTree -ProcId ([int]$Process.Id)
        }
    } catch {
        # already gone
    }
}

function Get-ChromePath {
    $candidates = @(
        "${env:ProgramFiles}\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        (Join-Path $env:LocalAppData "Google\Chrome\Application\chrome.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

function Test-ChromeDebugApi {
    try {
        $null = Invoke-RestMethod -Uri "http://127.0.0.1:$ChromeDebugPort/json/version" -TimeoutSec 1
        return $true
    } catch {
        return $false
    }
}

function Stop-SharedAlgoChrome {
    $procs = @()
    try {
        $procs = @(Get-CimInstance Win32_Process -Filter "Name = 'chrome.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -and ($_.CommandLine -like "*indian-algo-all-strategies*") })
    } catch {
        $procs = @()
    }
    foreach ($p in $procs) {
        Stop-PidTree -ProcId ([int]$p.ProcessId)
    }
}

function Close-ChromeTabsForUrl {
    param([Parameter(Mandatory = $true)][string]$Url)
    if (-not (Test-ChromeDebugApi)) { return }
    $authority = ([uri]$Url).Authority
    $tabs = @()
    try {
        $tabs = @(Invoke-RestMethod -Uri "http://127.0.0.1:$ChromeDebugPort/json" -TimeoutSec 2)
    } catch {
        return
    }
    foreach ($tab in $tabs) {
        if ($tab.type -ne "page") { continue }
        if ([string]$tab.url -notlike "*${authority}*") { continue }
        Write-Host "  Closing old Chrome tab ($authority)..." -ForegroundColor DarkYellow
        try {
            Invoke-RestMethod -Uri "http://127.0.0.1:$ChromeDebugPort/json/close/$($tab.id)" -TimeoutSec 2 | Out-Null
        } catch { }
    }
}

function Open-StrategyInChrome {
    param([Parameter(Mandatory = $true)][string]$Url)
    $chrome = Get-ChromePath
    if (-not $chrome) {
        Write-Host "Chrome not found. Open $Url manually." -ForegroundColor DarkYellow
        return
    }

    # Shared profile must run with remote debugging so we can close/reopen one strategy tab.
    if (-not (Test-ChromeDebugApi)) {
        Write-Host "  Starting shared Chrome (enabling tab control)..." -ForegroundColor DarkYellow
        Stop-SharedAlgoChrome
        Start-Sleep -Seconds 1
        $argLine = '--user-data-dir="' + $ChromeProfileDir + '" --remote-debugging-port=' + $ChromeDebugPort + ' --no-first-run --no-default-browser-check "' + $Url + '"'
        Start-Process -FilePath $chrome -ArgumentList $argLine | Out-Null
        Start-Sleep -Seconds 2
        return
    }

    Close-ChromeTabsForUrl -Url $Url
    Start-Sleep -Milliseconds 400
    try {
        Invoke-RestMethod -Uri ("http://127.0.0.1:$ChromeDebugPort/json/new?" + $Url) -Method Put -TimeoutSec 3 | Out-Null
    } catch {
        $argLine = '--user-data-dir="' + $ChromeProfileDir + '" --remote-debugging-port=' + $ChromeDebugPort + ' --no-first-run --no-default-browser-check "' + $Url + '"'
        Start-Process -FilePath $chrome -ArgumentList $argLine | Out-Null
    }
}

$children = @()

try {
    Write-Host "$StrategyName - starting backend + frontend" -ForegroundColor Cyan
    Write-Host "Frontend: $FrontendUrl"
    Write-Host "Backend : http://127.0.0.1:$BackendPort"
    Write-Host "Login   : admin / admin"
    Write-Host ""

    Write-Host "Stopping any previous $StrategyName instance on ports $FrontendPort / $BackendPort..." -ForegroundColor Yellow
    Clear-ListenPort -Port $FrontendPort
    Clear-ListenPort -Port $BackendPort
    Close-ChromeTabsForUrl -Url $FrontendUrl
    Start-Sleep -Seconds 2

    $children += Start-ManagedProcess -Name "Backend" -Command "npm run worker"
    Start-Sleep -Seconds 3

    $buildId = Join-Path $root ".next\BUILD_ID"
    $needsBuild = -not (Test-Path $buildId)
    if (-not $needsBuild) {
        $buildTime = (Get-Item $buildId).LastWriteTimeUtc
        $newestSrc = Get-ChildItem -Path (Join-Path $root "src") -Recurse -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -First 1
        if ($null -ne $newestSrc -and $newestSrc.LastWriteTimeUtc -gt $buildTime) {
            $needsBuild = $true
        }
    }
    if ($needsBuild) {
        Write-Host "Building frontend (new or changed source)..." -ForegroundColor Yellow
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build failed." }
    } else {
        Write-Host "Using existing production build (.next is up to date)." -ForegroundColor DarkGray
    }

    $children += Start-ManagedProcess -Name "Frontend" -Command "npm run start"
    Start-Sleep -Seconds 4

    Open-StrategyInChrome -Url $FrontendUrl
    Write-Host "Opened Chrome tab: $FrontendUrl (old tab for this port closed if it existed)" -ForegroundColor Green

    Write-Host "Started. Press ENTER to stop backend + frontend (Chrome stays open)." -ForegroundColor Green
    Write-Host "Re-run this CMD anytime - old ports are freed and the Chrome tab is replaced."

    while ($true) {
        foreach ($child in $children) {
            if ($child.Process.HasExited) {
                Write-Host "$($child.Name) stopped (exit $($child.Process.ExitCode))." -ForegroundColor DarkYellow
                return
            }
        }
        if ([Console]::KeyAvailable) {
            $key = [Console]::ReadKey($true)
            if ($key.Key -eq "Enter") { break }
        }
        Start-Sleep -Milliseconds 500
    }
}
finally {
    Write-Host ""
    Write-Host "Stopping $StrategyName backend + frontend..." -ForegroundColor Yellow
    foreach ($child in $children) {
        Stop-ProcessTree -Process $child.Process
    }
    try { Clear-ListenPort -Port $FrontendPort } catch { }
    try { Clear-ListenPort -Port $BackendPort } catch { }
    Write-Host "Stopped. Chrome left open (shared with other strategies)." -ForegroundColor Green
}
