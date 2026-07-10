$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root

$StrategyName = "Strategy 4"
$FrontendUrl = "http://localhost:3003"
$FrontendPort = 3003
$BackendPort = 8003
$ChromeProfileDir = Join-Path $env:TEMP "indian-algo-all-strategies"

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

function Open-StrategyInChrome {
    param([Parameter(Mandatory = $true)][string]$Url)
    $chrome = Get-ChromePath
    if (-not $chrome) {
        Write-Host "Chrome not found. Open $Url manually." -ForegroundColor DarkYellow
        return
    }
    $argLine = '--user-data-dir="' + $ChromeProfileDir + '" --no-first-run --no-default-browser-check ' + $Url
    Start-Process -FilePath $chrome -ArgumentList $argLine | Out-Null
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
    Write-Host "Opened in shared Chrome window: $FrontendUrl" -ForegroundColor Green

    Write-Host "Started. Press ENTER to stop backend + frontend (Chrome stays open)." -ForegroundColor Green
    Write-Host "Re-run this CMD anytime - old ports are freed automatically."

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
