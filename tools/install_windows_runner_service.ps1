param(
    [string]$RegistrationToken = "",
    [string]$RemoveToken = "",
    [string]$RunnerRoot = "C:\\actions-runner",
    [string]$RepositoryUrl = "https://github.com/adelemam84/-physics-edu-agent",
    [string]$RunnerName = "physics-windows-runner",
    [string]$WorkFolder = "_work"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this script from PowerShell opened with Run as administrator."
    }
}

function Get-RunnerListeners {
    @(Get-CimInstance Win32_Process -Filter "Name='Runner.Listener.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($RunnerRoot, [System.StringComparison]::OrdinalIgnoreCase) })
}

function Stop-InteractiveRunnerListeners {
    $listeners = Get-RunnerListeners
    foreach ($listener in $listeners) {
        $cmd = [string]$listener.CommandLine
        if ($cmd -match "\brun\b" -and $cmd -notmatch "--startuptype\s+service") {
            Write-Host "Stopping interactive Runner.Listener PID=$($listener.ProcessId)"
            Stop-Process -Id $listener.ProcessId -Force -ErrorAction Stop
        }
    }
    Start-Sleep -Seconds 2
}

function Get-RunnerService {
    $serviceFile = Join-Path $RunnerRoot ".service"
    if (Test-Path $serviceFile) {
        $name = (Get-Content $serviceFile -Raw).Trim()
        if ($name) {
            return Get-Service -Name $name -ErrorAction SilentlyContinue
        }
    }
    return Get-Service "actions.runner.*" -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "*$RunnerName*" } |
        Select-Object -First 1
}

Assert-Administrator

if (-not (Test-Path $RunnerRoot)) { throw "Runner directory not found: $RunnerRoot" }
$configCmd = Join-Path $RunnerRoot "config.cmd"
if (-not (Test-Path $configCmd)) { throw "config.cmd not found under $RunnerRoot" }

Set-Location $RunnerRoot
Write-Host "=== GitHub Actions Windows runner service bootstrap ==="
Write-Host "RunnerRoot=$RunnerRoot"
Write-Host "RepositoryUrl=$RepositoryUrl"
Write-Host "RunnerName=$RunnerName"

$existingService = Get-RunnerService
if ($existingService) {
    Write-Host "Runner service already exists: $($existingService.Name)"
    Set-Service -Name $existingService.Name -StartupType Automatic
    if ($existingService.Status -ne "Running") { Start-Service -Name $existingService.Name }
    sc.exe failure $existingService.Name reset= 86400 actions= restart/5000/restart/15000/restart/60000 | Out-Host
    sc.exe failureflag $existingService.Name 1 | Out-Host
    Start-Sleep -Seconds 3
    $existingService = Get-Service -Name $existingService.Name
    if ($existingService.Status -ne "Running") { throw "Runner service exists but is not Running." }
    $listeners = Get-RunnerListeners
    Write-Host "RUNNER_SERVICE_OK service=$($existingService.Name) status=$($existingService.Status) listeners=$($listeners.Count)"
    exit 0
}

Write-Host "No Windows runner service is configured yet."
Stop-InteractiveRunnerListeners

$runnerConfig = Join-Path $RunnerRoot ".runner"
$alreadyConfigured = Test-Path $runnerConfig
if ($alreadyConfigured) {
    try {
        $stored = Get-Content $runnerConfig -Raw | ConvertFrom-Json
        if ($stored.agentName) { $RunnerName = [string]$stored.agentName }
        if ($stored.workFolder) { $WorkFolder = [string]$stored.workFolder }
    } catch {
        Write-Warning "Could not parse .runner; continuing with supplied runner name/work folder."
    }
    if (-not $RemoveToken) {
        throw "Runner is already configured without a Windows Service. Supply -RemoveToken and -RegistrationToken from GitHub Settings > Actions > Runners."
    }
    if (-not $RegistrationToken) { throw "RegistrationToken is required to re-register the runner as a Windows Service." }
    Write-Host "Removing existing non-service runner registration..."
    & $configCmd remove --token $RemoveToken
    if ($LASTEXITCODE -ne 0) { throw "config.cmd remove failed with exit code $LASTEXITCODE" }
}

if (-not $RegistrationToken) { throw "RegistrationToken is required to configure the Windows runner service." }

Write-Host "Configuring runner as Windows Service..."
$configArgs = @(
    "--url", $RepositoryUrl,
    "--token", $RegistrationToken,
    "--name", $RunnerName,
    "--work", $WorkFolder,
    "--unattended",
    "--replace",
    "--runasservice"
)
& $configCmd @configArgs
if ($LASTEXITCODE -ne 0) { throw "config.cmd service configuration failed with exit code $LASTEXITCODE" }

$service = Get-RunnerService
if (-not $service) { throw "Runner configuration completed but Windows Service was not found." }
Set-Service -Name $service.Name -StartupType Automatic
if ($service.Status -ne "Running") { Start-Service -Name $service.Name }
sc.exe failure $service.Name reset= 86400 actions= restart/5000/restart/15000/restart/60000 | Out-Host
sc.exe failureflag $service.Name 1 | Out-Host
Start-Sleep -Seconds 5
$service = Get-Service -Name $service.Name
$listeners = Get-RunnerListeners
if ($service.Status -ne "Running") { throw "Runner service is not Running after configuration." }
if ($listeners.Count -ne 1) { throw "Expected exactly one Runner.Listener after service installation, found $($listeners.Count)." }
if ([string]$listeners[0].CommandLine -notmatch "--startuptype\s+service") {
    throw "Runner.Listener is running, but not in service startup mode."
}
Write-Host "RUNNER_SERVICE_OK service=$($service.Name) status=$($service.Status) startup=Automatic listener_pid=$($listeners[0].ProcessId)"
