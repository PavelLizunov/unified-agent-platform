param(
  [string]$GitUrl = "",
  [string]$Branch = "master"
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($GitUrl)) {
  $previousErrorActionPreference = $ErrorActionPreference
  $ErrorActionPreference = "SilentlyContinue"
  $remoteOutput = git remote get-url origin 2>$null
  $remoteExitCode = $LASTEXITCODE
  $ErrorActionPreference = $previousErrorActionPreference
  if ($remoteExitCode -eq 0) {
    $GitUrl = $remoteOutput
  }
}

if ([string]::IsNullOrWhiteSpace($GitUrl)) {
  Write-Host "git-remote-missing"
  Write-Host "No origin remote is configured. Provide -GitUrl or configure git remote add origin <url>."
  exit 0
}

Write-Host "== git remote =="
Write-Host $GitUrl

git ls-remote --heads $GitUrl $Branch
if ($LASTEXITCODE -ne 0) {
  throw "Cannot read branch '$Branch' from remote: $GitUrl"
}

Write-Host "git-remote-ok"
