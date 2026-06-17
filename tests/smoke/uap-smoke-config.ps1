$ErrorActionPreference = "Stop"

function Get-UapEnvValue {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string]$DefaultValue
  )

  $value = [Environment]::GetEnvironmentVariable($Name)
  if ([string]::IsNullOrWhiteSpace($value)) {
    return $DefaultValue
  }

  return $value
}

$script:UapSshUser = Get-UapEnvValue -Name "UAP_SSH_USER" -DefaultValue "uap"
$script:UapK3sServerHost = Get-UapEnvValue -Name "UAP_K3S_SERVER_HOST" -DefaultValue "100.106.223.120"
$script:UapK3sServerName = Get-UapEnvValue -Name "UAP_K3S_SERVER_NAME" -DefaultValue "uap-home-1"
$script:UapK3sServerTailnetIp = Get-UapEnvValue -Name "UAP_K3S_SERVER_TAILNET_IP" -DefaultValue "100.106.223.120"
$script:UapK3sAgentHost = Get-UapEnvValue -Name "UAP_K3S_AGENT_HOST" -DefaultValue "100.94.228.67"
$script:UapK3sAgentName = Get-UapEnvValue -Name "UAP_K3S_AGENT_NAME" -DefaultValue "uap-home-2"
$script:UapSopsAgeKeyFile = Get-UapEnvValue -Name "UAP_SOPS_AGE_KEY_FILE" -DefaultValue "/home/uap/.config/sops/age/keys.txt"

$hostsFromEnv = [Environment]::GetEnvironmentVariable("UAP_SSH_HOSTS")
if ([string]::IsNullOrWhiteSpace($hostsFromEnv)) {
  $script:UapSmokeHosts = @($script:UapK3sServerHost, $script:UapK3sAgentHost) |
    Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
    Select-Object -Unique
}
else {
  $script:UapSmokeHosts = $hostsFromEnv.Split(",") |
    ForEach-Object { $_.Trim() } |
    Where-Object { $_ -ne "" } |
    Select-Object -Unique
}

$script:UapKnownHosts = Join-Path $env:TEMP "uap_smoke_known_hosts"
$script:UapSshOptions = @(
  "-o", "BatchMode=yes",
  "-o", "StrictHostKeyChecking=no",
  "-o", "UserKnownHostsFile=$script:UapKnownHosts",
  "-o", "ConnectTimeout=10"
)

function Get-UapSshTarget {
  param([Parameter(Mandatory = $true)][string]$HostName)
  return "$script:UapSshUser@$HostName"
}

function Invoke-UapSsh {
  param(
    [Parameter(Mandatory = $true)][string]$Target,
    [Parameter(Mandatory = $true)][string]$Command
  )

  ssh @script:UapSshOptions $Target $Command
  if ($LASTEXITCODE -ne 0) {
    throw "SSH command failed on $Target with exit code $LASTEXITCODE"
  }
}

function Invoke-UapScp {
  param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Destination
  )

  scp @script:UapSshOptions $Source $Destination
  if ($LASTEXITCODE -ne 0) {
    throw "SCP failed with exit code $LASTEXITCODE"
  }
}
