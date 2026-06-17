param(
  [string]$Prefix = "UAP_S3"
)

$ErrorActionPreference = "Stop"

$required = @(
  "${Prefix}_ENDPOINT",
  "${Prefix}_BUCKET",
  "${Prefix}_REGION",
  "${Prefix}_ACCESS_KEY",
  "${Prefix}_SECRET_KEY"
)

$missing = @()
foreach ($name in $required) {
  $value = [Environment]::GetEnvironmentVariable($name)
  if ([string]::IsNullOrWhiteSpace($value)) {
    $missing += $name
  }
}

if ($missing.Count -gt 0) {
  Write-Host "s3-env-missing"
  foreach ($name in $missing) {
    Write-Host "missing: $name"
  }
  exit 0
}

Write-Host "s3-env-ok"
Write-Host "Endpoint, bucket, region, access key, and secret key are present in environment."
Write-Host "Values intentionally not printed."
