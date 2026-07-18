param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [string]$BundleZip = (Join-Path (Resolve-Path "$PSScriptRoot\..").Path "listingo-data-bundle.zip")
)

$projectRoot = Resolve-Path $ProjectRoot
$tempDir = Join-Path $projectRoot "restore_tmp"
$bundlePath = Resolve-Path $BundleZip

if (-not (Test-Path $bundlePath)) {
    throw "Bundle not found: $bundlePath"
}

if (Test-Path $tempDir) { Remove-Item -Path $tempDir -Recurse -Force }
New-Item -ItemType Directory -Path $tempDir | Out-Null

Expand-Archive -Path $bundlePath -DestinationPath $tempDir -Force

$dataDir = Join-Path $projectRoot "data"
New-Item -ItemType Directory -Path (Join-Path $dataDir "uploads"), (Join-Path $dataDir "results"), (Join-Path $dataDir "exports") -Force | Out-Null

Copy-Item -Path (Join-Path $tempDir "listingo.sqlite3") -Destination (Join-Path $dataDir "listingo.sqlite3") -Force
Copy-Item -Path (Join-Path $tempDir "uploads\*") -Destination (Join-Path $dataDir "uploads") -Recurse -Force
Copy-Item -Path (Join-Path $tempDir "results\*") -Destination (Join-Path $dataDir "results") -Recurse -Force
Copy-Item -Path (Join-Path $tempDir "exports\*") -Destination (Join-Path $dataDir "exports") -Recurse -Force

Remove-Item -Path $tempDir -Recurse -Force
Write-Host "Data restored from $bundlePath"
