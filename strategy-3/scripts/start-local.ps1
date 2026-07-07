$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root

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

$children = @()

try {
    Write-Host "Strategy 3 - starting backend + frontend" -ForegroundColor Cyan
    Write-Host "Frontend: http://localhost:3002"
    Write-Host "Backend : http://127.0.0.1:8002"
    Write-Host "Login   : admin / admin"
    Write-Host ""

    $children += Start-ManagedProcess -Name "Backend" -Command "npm run worker"
    Start-Sleep -Seconds 3
    $children += Start-ManagedProcess -Name "Frontend" -Command "npm run dev"

    Write-Host "Started. Press ENTER in this window to stop backend + frontend." -ForegroundColor Green
    Write-Host "Closing this CMD window will also close both processes."

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
    Write-Host "Stopping Strategy 3 backend + frontend..." -ForegroundColor Yellow
    foreach ($child in $children) {
        Stop-ProcessTree -Process $child.Process
    }
    Write-Host "Stopped." -ForegroundColor Green
}
