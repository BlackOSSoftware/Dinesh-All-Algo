$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root

$FrontendUrl = "http://localhost:3001"
$ChromeProfileName = "indian-algo-strategy-2"

function Start-ManagedProcess {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][string]$Command
    )

    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = "cmd.exe"
    $psi.Arguments = "/d /s /c `"$Command`""
    $psi.WorkingDirectory = $root
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $false

    $process = [System.Diagnostics.Process]::Start($psi)
    [pscustomobject]@{ Name = $Name; Process = $process }
}

function Stop-ProcessTree {
    param([System.Diagnostics.Process]$Process)

    if ($null -ne $Process -and -not $Process.HasExited) {
        taskkill.exe /PID $Process.Id /T /F | Out-Null
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

function Start-ChromeApp {
    param(
        [Parameter(Mandatory=$true)][string]$Url,
        [Parameter(Mandatory=$true)][string]$ProfileName
    )

    $chrome = Get-ChromePath
    if (-not $chrome) {
        Write-Host "Chrome not found. Open $Url manually." -ForegroundColor DarkYellow
        return $null
    }

    $profileDir = Join-Path $env:TEMP $ProfileName
    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $chrome
    $psi.Arguments = "--new-window `"$Url`" --user-data-dir=`"$profileDir`" --no-first-run --no-default-browser-check"
    $psi.UseShellExecute = $false
    return [System.Diagnostics.Process]::Start($psi)
}

$children = @()

try {
    Write-Host "Strategy 2 - starting backend + frontend" -ForegroundColor Cyan
    Write-Host "Frontend: $FrontendUrl"
    Write-Host "Backend : http://127.0.0.1:8001"
    Write-Host "Login   : admin / admin"
    Write-Host ""

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

    $chrome = Start-ChromeApp -Url $FrontendUrl -ProfileName $ChromeProfileName
    if ($null -ne $chrome) {
        $children += [pscustomobject]@{ Name = "Chrome"; Process = $chrome }
        Write-Host "Opened Chrome window: $FrontendUrl" -ForegroundColor Green
    }

    Write-Host "Started. Press ENTER in this window to stop backend, frontend, and Chrome." -ForegroundColor Green
    Write-Host "Closing this CMD window will also close all processes."

    while ($true) {
        foreach ($child in $children) {
            if ($child.Process.HasExited) {
                throw "$($child.Name) exited with code $($child.Process.ExitCode)."
            }
        }

        if ([Console]::KeyAvailable) {
            $key = [Console]::ReadKey($true)
            if ($key.Key -eq "Enter") {
                break
            }
        }

        Start-Sleep -Milliseconds 500
    }
}
finally {
    Write-Host ""
    Write-Host "Stopping Strategy 2 backend, frontend, and Chrome..." -ForegroundColor Yellow
    foreach ($child in $children) {
        Stop-ProcessTree -Process $child.Process
    }
    Write-Host "Stopped." -ForegroundColor Green
}
