param(
    [string]$TaskName = "Call Notifier Receiver",
    [string]$FirewallRuleName = "Call Notifier Receiver UDP 45832",
    [string]$HotspotProfileName = ""
)

$ErrorActionPreference = "Stop"
$projectDirectory = Split-Path -Parent $PSScriptRoot
$pythonwPath = Join-Path $projectDirectory "venv\Scripts\pythonw.exe"
$pythonPath = Join-Path $projectDirectory "venv\Scripts\python.exe"
$launcherPath = Join-Path $PSScriptRoot "run_receiver.py"

foreach ($path in @($pythonwPath, $pythonPath, $launcherPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required file is missing: $path"
    }
}

$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$escapedUserId = [System.Security.SecurityElement]::Escape($userId)
$escapedPythonwPath = [System.Security.SecurityElement]::Escape($pythonwPath)
$escapedLauncherPath = [System.Security.SecurityElement]::Escape($launcherPath)
$escapedProjectDirectory = [System.Security.SecurityElement]::Escape($projectDirectory)
$taskXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Run the call notifier receiver after sign-in or workstation unlock.</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>$escapedUserId</UserId>
    </LogonTrigger>
    <SessionStateChangeTrigger>
      <Enabled>true</Enabled>
      <StateChange>SessionUnlock</StateChange>
      <UserId>$escapedUserId</UserId>
    </SessionStateChangeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$escapedUserId</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$escapedPythonwPath</Command>
      <Arguments>&quot;$escapedLauncherPath&quot;</Arguments>
      <WorkingDirectory>$escapedProjectDirectory</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

Register-ScheduledTask -TaskName $TaskName -Xml $taskXml -Force | Out-Null

$existingRule = Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue
if ($existingRule) {
    $existingRule | Remove-NetFirewallRule
}
New-NetFirewallRule `
    -DisplayName $FirewallRuleName `
    -Direction Inbound `
    -Action Allow `
    -Program $pythonPath `
    -Protocol UDP `
    -LocalPort 45832 `
    -Profile Any | Out-Null

if ($HotspotProfileName) {
    & netsh.exe wlan set profileparameter name="$HotspotProfileName" connectionmode=auto | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not enable auto-connect for Wi-Fi profile: $HotspotProfileName"
    }
    Write-Output "Wi-Fi auto-connect enabled: $HotspotProfileName"
}

Write-Output "Scheduled task created: $TaskName"
Write-Output "Firewall rule created: $FirewallRuleName"
