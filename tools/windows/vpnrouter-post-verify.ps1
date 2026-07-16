param([Parameter(Mandatory = $true)][string]$CommitSha)

$ErrorActionPreference = 'Stop'
if ($CommitSha -notmatch '^[0-9a-f]{40}$') {
    throw 'Invalid default-branch commit SHA'
}

$root = Join-Path 'C:\uap\post-verify' $CommitSha
$zip = "$root.zip"
$expand = "$root-expand"
New-Item -ItemType Directory -Path (Split-Path -Parent $root) -Force | Out-Null
Remove-Item -LiteralPath $root, $zip, $expand -Recurse -Force -ErrorAction SilentlyContinue
Invoke-WebRequest -UseBasicParsing `
    "https://github.com/PavelLizunov/VPNRouter/archive/$CommitSha.zip" `
    -OutFile $zip
Expand-Archive -LiteralPath $zip -DestinationPath $expand -Force
$source = Get-ChildItem -LiteralPath $expand -Directory | Select-Object -First 1
Move-Item -LiteralPath $source.FullName -Destination $root

$dotnet = 'C:\uap\dotnet\dotnet.exe'
& $dotnet restore (Join-Path $root 'VPNRouter.CLI\VPNRouter.CLI.csproj') --verbosity quiet
if ($LASTEXITCODE) { exit $LASTEXITCODE }
& $dotnet restore (Join-Path $root 'VPNRouter.Tests\VPNRouter.Tests.csproj') --verbosity quiet
if ($LASTEXITCODE) { exit $LASTEXITCODE }
& $dotnet build (Join-Path $root 'VPNRouter.CLI\VPNRouter.CLI.csproj') `
    -c Release --no-restore --verbosity minimal
if ($LASTEXITCODE) { exit $LASTEXITCODE }
& $dotnet test (Join-Path $root 'VPNRouter.Tests\VPNRouter.Tests.csproj') `
    -c Release --no-restore `
    --filter 'FullyQualifiedName!~Headless&FullyQualifiedName!~PageScreenshot&FullyQualifiedName!~VisualDiff' `
    --logger 'console;verbosity=minimal'
if ($LASTEXITCODE) { exit $LASTEXITCODE }
Write-Output "windows-brat-post-verify-ok $CommitSha"
