param([ValidateSet('start','stop','status','reset','trigger')][string]$Action = 'status')

# Control script for the Nereus Tankers maritime RTI demo.
# The simulator runs LOCALLY (python src/local_sim.py) so it does not consume Fabric capacity.
$root    = $PSScriptRoot
$state   = Get-Content (Join-Path $root ".state.json") -Raw | ConvertFrom-Json
$config  = Get-Content (Join-Path $root "config.json") -Raw | ConvertFrom-Json
$api     = "https://api.fabric.microsoft.com/v1/workspaces/$($state.ws)/items"
$pidFile = Join-Path $root ".sim.pid"
$logFile = Join-Path $root "sim.log"
$subArgs = if ($config.subscription) { @("--subscription", $config.subscription) } else { @() }

function Get-Token($resource) { az account get-access-token @subArgs --resource $resource --query accessToken -o tsv }
$h = @{ Authorization = "Bearer $(Get-Token 'https://api.fabric.microsoft.com')" }

function Get-LocalSim {
    if (Test-Path $pidFile) {
        $p = Get-Process -Id ([int](Get-Content $pidFile)) -ErrorAction SilentlyContinue
        if ($p -and $p.ProcessName -like 'python*') { return $p }
    }
    $null
}

function Stop-Sim {
    $p = Get-LocalSim
    if ($p) { Stop-Process -Id $p.Id -Force; Write-Host "Stopped local simulator (PID $($p.Id))" }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
    if ($state.nb_sim) {
        foreach ($j in (Invoke-RestMethod "$api/$($state.nb_sim)/jobs/instances" -Headers $h).value | Where-Object { $_.status -in 'InProgress','NotStarted' }) {
            Invoke-WebRequest -Method Post "$api/$($state.nb_sim)/jobs/instances/$($j.id)/cancel" -Headers $h | Out-Null
            Write-Host "Cancelled Spark simulator run $($j.id)"
        }
    }
}

function Start-Sim {
    if (Get-LocalSim) { Write-Host "Already running."; return }
    $p = Start-Process python -ArgumentList "-u", "`"$root\src\local_sim.py`"" -WorkingDirectory $root -WindowStyle Hidden `
        -RedirectStandardOutput $logFile -RedirectStandardError "$logFile.err" -PassThru
    $p.Id | Out-File $pidFile
    Write-Host "Local simulator started (PID $($p.Id)) - data visible on the dashboard in ~20 seconds. Log: $logFile"
}

function Reset-Data {
    Write-Host "Reloading reference tables (removes demo maintenance orders)..."
    $r = Invoke-WebRequest -Method Post "$api/$($state.nb_setup)/jobs/instances?jobType=RunNotebook" -Headers $h -ContentType "application/json" -Body '{}'
    $loc = "$($r.Headers.Location)"
    do { Start-Sleep 15; $s = (Invoke-RestMethod $loc -Headers $h).status } while ($s -in 'NotStarted','InProgress')
    Write-Host "Reference data reload: $s"
}

function Show-Status {
    $p = Get-LocalSim
    Write-Host ("Simulator: " + $(if ($p) { "RUNNING locally (PID $($p.Id), started $($p.StartTime))" } else { "STOPPED" }))
    $b = @{ db = "FleetEH"; csl = "VesselPositions | where timestamp > ago(2m) | summarize arg_max(timestamp, *) by vessel_id | project timestamp, vessel_name, speed_knots, nav_status, destination" } | ConvertTo-Json
    $r = Invoke-RestMethod -Method Post "$($state.kusto_uri)/v2/rest/query" -Headers @{ Authorization = "Bearer $(Get-Token 'https://kusto.kusto.windows.net')" } `
        -ContentType "application/json; charset=utf-8" -Body $b
    ($r | Where-Object { $_.TableKind -eq 'PrimaryResult' }).Rows | ForEach-Object { Write-Host ("  " + ($_ -join ' | ')) }
}

switch ($Action) {
    'start'   { Start-Sim }
    'stop'    { Stop-Sim; Write-Host "Stopped." }
    'reset'   { Stop-Sim; Reset-Data; Start-Sim }
    'trigger' { python "$root\src\local_sim.py" trigger }
    'status'  { Show-Status }
}
