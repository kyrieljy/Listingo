param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
)

$projectRoot = Resolve-Path $ProjectRoot
$backupDir = Join-Path $projectRoot "backup"
$bundleDir = Join-Path $backupDir "listingo-data-bundle"
$zipPath = Join-Path $projectRoot "listingo-data-bundle.zip"

New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
if (Test-Path $bundleDir) { Remove-Item -Path $bundleDir -Recurse -Force }
New-Item -ItemType Directory -Path $bundleDir | Out-Null

Copy-Item -Path (Join-Path $projectRoot "data\listingo.sqlite3") -Destination (Join-Path $bundleDir "listingo.sqlite3") -Force
Copy-Item -Path (Join-Path $projectRoot "data\uploads") -Destination (Join-Path $bundleDir "uploads") -Recurse -Force
Copy-Item -Path (Join-Path $projectRoot "data\results") -Destination (Join-Path $bundleDir "results") -Recurse -Force
Copy-Item -Path (Join-Path $projectRoot "data\exports") -Destination (Join-Path $bundleDir "exports") -Recurse -Force

if (Test-Path $zipPath) { Remove-Item -Path $zipPath -Force }
Compress-Archive -Path (Join-Path $bundleDir "*") -DestinationPath $zipPath -Force

Write-Host "Data backup created:"
Write-Host ("  $zipPath")
