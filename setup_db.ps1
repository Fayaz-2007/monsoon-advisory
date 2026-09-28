<#
.SYNOPSIS
  One-step, no-admin setup of a local PostgreSQL 16 + PostGIS database for monsoon-advisory.

.DESCRIPTION
  1. Downloads the portable PostgreSQL binaries zip (EnterpriseDB) and the PostGIS bundle
     zip (OSGeo) into <ToolsDir>\downloads (skipped if already there; PostGIS MD5-verified).
  2. Extracts them to <ToolsDir>\pgsql and merges PostGIS in without overwriting PostgreSQL files.
  3. Initialises a cluster in <DataDir> (localhost only, scram-sha-256, generated passwords).
  4. Starts it, creates role monsoon_app, database monsoon and the postgis extension.
  5. Writes DATABASE_URL and PG_SUPERUSER_PASSWORD into <EnvFile> (created from .env.example;
     an existing file is backed up to .env.bak and only those two lines are replaced).
  6. Verifies: connects as monsoon_app and prints postgis_full_version().

  Re-running is safe: finished steps are detected and skipped. Nothing needs admin/UAC.

.EXAMPLE
  setup_db.bat
.EXAMPLE
  setup_db.bat -ToolsDir D:\tmp\tools -DataDir D:\tmp\pgdata -Port 5440 -EnvFile D:\tmp\.env
#>
[CmdletBinding()]
param(
    # Path defaults are resolved below: $PSScriptRoot is empty inside param() on Windows PowerShell 5.1.
    [string]$ToolsDir = "",
    [string]$DataDir = "",
    [int]$Port = 5432,
    [string]$EnvFile = "",
    [string]$EnvExample = "",
    [string]$PgVersion = "16.15",
    [string]$PostgisVersion = "3.6.2",
    [string]$DbName = "monsoon",
    [string]$AppUser = "monsoon_app"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Step([string]$msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Info([string]$msg) { Write-Host "    $msg" }
function Fail([string]$msg) { Write-Host "`n[setup_db] ERROR: $msg" -ForegroundColor Red; exit 1 }
function Check-Exit([string]$what) { if ($LASTEXITCODE -ne 0) { Fail "$what failed (exit code $LASTEXITCODE)" } }
function New-Password { [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N").Substring(0, 8) }

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $ToolsDir) { $ToolsDir = Join-Path $Root "..\tools" }
if (-not $DataDir) { $DataDir = Join-Path $Root ".pgdata" }
if (-not $EnvFile) { $EnvFile = Join-Path $Root "backend\.env" }
if (-not $EnvExample) { $EnvExample = Join-Path $Root "backend\.env.example" }

function Full([string]$p) { [IO.Path]::GetFullPath($p) }
$ToolsDir = Full $ToolsDir; $DataDir = Full $DataDir; $EnvFile = Full $EnvFile; $EnvExample = Full $EnvExample
$Downloads = Join-Path $ToolsDir "downloads"
$PgRoot = Join-Path $ToolsDir "pgsql"
$Bin = Join-Path $PgRoot "bin"

$PgZipName = "postgresql-$PgVersion-1-windows-x64-binaries.zip"
$PgUrl = "https://get.enterprisedb.com/postgresql/$PgZipName"
$GisZipName = "postgis-bundle-pg16-${PostgisVersion}x64.zip"
$GisUrl = "https://download.osgeo.org/postgis/windows/pg16/$GisZipName"

Write-Host "monsoon-advisory database setup" -ForegroundColor Green
Info "tools : $ToolsDir"
Info "data  : $DataDir"
Info "port  : $Port"
Info "env   : $EnvFile"

# Use the Windows built-in tools explicitly: Git for Windows can put GNU tar/curl first on PATH,
# and GNU tar misreads "C:\..." as a remote host.
$Sys32 = Join-Path $env:SystemRoot "System32"
$Curl = Join-Path $Sys32 "curl.exe"
$Tar = Join-Path $Sys32 "tar.exe"
$Robocopy = Join-Path $Sys32 "robocopy.exe"
foreach ($t in @($Curl, $Tar, $Robocopy)) {
    if (-not (Test-Path $t)) { Fail "$t not found (needs Windows 10 version 1803 or newer)." }
}
if (-not (Test-Path $EnvExample)) { Fail ".env.example not found at $EnvExample" }

# ---------------------------------------------------------------------------
Step "1/6 Download PostgreSQL $PgVersion and PostGIS $PostgisVersion"
New-Item -ItemType Directory -Force -Path $Downloads | Out-Null

function Get-File([string]$url, [string]$dest, [long]$minBytes) {
    if ((Test-Path $dest) -and ((Get-Item $dest).Length -ge $minBytes)) {
        Info "cached: $(Split-Path $dest -Leaf)"
        return
    }
    Info "downloading $url"
    $part = "$dest.part"
    & $Curl -L --fail --retry 3 --retry-delay 5 --connect-timeout 60 -sS -o $part $url
    Check-Exit "download of $url"
    if ((Get-Item $part).Length -lt $minBytes) { Fail "download of $url is too small - server error?" }
    Move-Item -Force $part $dest
    Info ("saved {0} ({1:N0} MB)" -f (Split-Path $dest -Leaf), ((Get-Item $dest).Length / 1MB))
}

$PgZip = Join-Path $Downloads $PgZipName
$GisZip = Join-Path $Downloads $GisZipName
Get-File $PgUrl $PgZip 200MB
Get-File $GisUrl $GisZip 50MB

$md5Line = (& $Curl -L --fail -sS "$GisUrl.md5")
Check-Exit "download of PostGIS checksum"
$expected = ($md5Line -split "\s+")[0].ToLower()
$actual = (Get-FileHash -Algorithm MD5 $GisZip).Hash.ToLower()
if ($expected -ne $actual) { Remove-Item $GisZip; Fail "PostGIS zip MD5 mismatch (expected $expected, got $actual). Re-run to download again." }
Info "PostGIS MD5 verified ($actual)"

# ---------------------------------------------------------------------------
Step "2/6 Extract binaries"
if (Test-Path (Join-Path $Bin "postgres.exe")) {
    Info "PostgreSQL already extracted"
} else {
    & $Tar -xf $PgZip -C $ToolsDir
    Check-Exit "extracting $PgZipName"
    Info "PostgreSQL extracted to $PgRoot"
}
$postgisControl = Join-Path $PgRoot "share\extension\postgis.control"
if (Test-Path $postgisControl) {
    Info "PostGIS already merged"
} else {
    $tmp = Join-Path $ToolsDir "_postgis_tmp"
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    & $Tar -xf $GisZip -C $tmp
    Check-Exit "extracting $GisZipName"
    $bundle = Get-ChildItem $tmp -Directory | Select-Object -First 1
    # /XC /XN /XO: copy only files that do not already exist (never overwrite PostgreSQL's own DLLs)
    & $Robocopy $bundle.FullName $PgRoot /E /XC /XN /XO /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { Fail "robocopy failed merging PostGIS (exit $LASTEXITCODE)" }
    Remove-Item -Recurse -Force $tmp
    if (-not (Test-Path $postgisControl)) { Fail "PostGIS merge did not produce $postgisControl" }
    Info "PostGIS merged into $PgRoot"
}
& (Join-Path $Bin "postgres.exe") --version
Check-Exit "postgres --version"

# ---------------------------------------------------------------------------
Step "3/6 Initialise cluster"
$env:PGPORT = "$Port"
$superPw = $null
$appPw = $null
$existingEnv = @{}
if (Test-Path $EnvFile) {
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match '^\s*([A-Z_]+)\s*=\s*(.*)$') { $existingEnv[$Matches[1]] = $Matches[2].Trim() }
    }
}

if (Test-Path (Join-Path $DataDir "PG_VERSION")) {
    Info "cluster already exists - reusing it"
    $superPw = $existingEnv["PG_SUPERUSER_PASSWORD"]
    if (-not $superPw -or $superPw -eq "CHANGE_ME") {
        Fail "cluster exists but PG_SUPERUSER_PASSWORD is not in $EnvFile. Delete $DataDir to start fresh."
    }
    if ($existingEnv["DATABASE_URL"] -match "://${AppUser}:([^@]+)@") { $appPw = $Matches[1] }
} else {
    $listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($listening) { Fail "port $Port is already in use by another program. Re-run with -Port <free port>." }
    $superPw = New-Password
    $pwFile = [IO.Path]::GetTempFileName()
    try {
        [IO.File]::WriteAllText($pwFile, $superPw)
        & (Join-Path $Bin "initdb.exe") -D $DataDir -U postgres "--pwfile=$pwFile" -A scram-sha-256 -E UTF8 --locale=C | Out-Null
        Check-Exit "initdb"
    } finally {
        Remove-Item -Force $pwFile -ErrorAction SilentlyContinue
    }
    $conf = @"

# --- monsoon-advisory local dev overrides (setup_db) ---
listen_addresses = 'localhost'
port = $Port
shared_buffers = 512MB
work_mem = 64MB
maintenance_work_mem = 512MB
max_wal_size = 4GB
"@
    Add-Content -Path (Join-Path $DataDir "postgresql.conf") -Value $conf -Encoding ASCII
    Info "cluster created in $DataDir (localhost:$Port only)"
}
if (-not $appPw) { $appPw = New-Password }

# ---------------------------------------------------------------------------
Step "4/6 Start server"
& (Join-Path $Bin "pg_isready.exe") -h localhost -p $Port -q
if ($LASTEXITCODE -eq 0) {
    Info "already running on localhost:$Port"
} else {
    $log = Join-Path $DataDir "server.log"
    # Start pg_ctl detached and wait only for pg_ctl itself (postgres keeps running after it exits).
    $out = [IO.Path]::GetTempFileName()
    $p = Start-Process -FilePath (Join-Path $Bin "pg_ctl.exe") -PassThru -WindowStyle Hidden `
        -ArgumentList @("-D", "`"$DataDir`"", "-l", "`"$log`"", "-w", "-t", "60", "start") `
        -RedirectStandardOutput $out
    $p.WaitForExit()
    Remove-Item $out -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 60; $i++) {
        & (Join-Path $Bin "pg_isready.exe") -h localhost -p $Port -q
        if ($LASTEXITCODE -eq 0) { break }
        Start-Sleep -Seconds 1
    }
    if ($LASTEXITCODE -ne 0) { Fail "server did not start - see $log" }
    Info "started on localhost:$Port"
}

# ---------------------------------------------------------------------------
Step "5/6 Create role, database and PostGIS"
$psql = Join-Path $Bin "psql.exe"
$env:PGPASSWORD = $superPw
$sql = @"
DO `$`$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$AppUser') THEN
    CREATE ROLE $AppUser LOGIN PASSWORD '$appPw';
  ELSE
    ALTER ROLE $AppUser LOGIN PASSWORD '$appPw';
  END IF;
END `$`$;
SELECT 'CREATE DATABASE $DbName OWNER $AppUser ENCODING ''UTF8'''
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DbName')\gexec
"@
$sqlFile = [IO.Path]::GetTempFileName()
try {
    [IO.File]::WriteAllText($sqlFile, $sql)
    & $psql -h localhost -p $Port -U postgres -d postgres -v ON_ERROR_STOP=1 -q -f $sqlFile
    Check-Exit "creating role/database"
} finally {
    Remove-Item -Force $sqlFile -ErrorAction SilentlyContinue
}
& $psql -h localhost -p $Port -U postgres -d $DbName -v ON_ERROR_STOP=1 -q `
    -c "CREATE EXTENSION IF NOT EXISTS postgis;" -c "GRANT ALL ON SCHEMA public TO $AppUser;"
Check-Exit "creating PostGIS extension"
Info "role '$AppUser', database '$DbName' and extension 'postgis' ready"

# ---------------------------------------------------------------------------
Step "6/6 Write $EnvFile and verify"
$dbUrl = "postgresql+psycopg2://${AppUser}:${appPw}@localhost:${Port}/${DbName}"
if (Test-Path $EnvFile) {
    Copy-Item -Force $EnvFile "$EnvFile.bak"
    $lines = Get-Content $EnvFile
    Info "existing file backed up to $(Split-Path $EnvFile -Leaf).bak"
} else {
    New-Item -ItemType Directory -Force -Path (Split-Path $EnvFile) | Out-Null
    $lines = @("# LOCAL DEV SECRETS - never commit (git-ignored). Generated by setup_db on $(Get-Date -Format yyyy-MM-dd).") + (Get-Content $EnvExample)
}
$hasUrl = $false; $hasSu = $false
$lines = foreach ($l in $lines) {
    if ($l -match '^\s*DATABASE_URL\s*=') { $hasUrl = $true; "DATABASE_URL=$dbUrl" }
    elseif ($l -match '^\s*PG_SUPERUSER_PASSWORD\s*=') { $hasSu = $true; "PG_SUPERUSER_PASSWORD=$superPw" }
    else { $l }
}
if (-not $hasUrl) { $lines += "DATABASE_URL=$dbUrl" }
if (-not $hasSu) { $lines += "PG_SUPERUSER_PASSWORD=$superPw" }
[IO.File]::WriteAllLines($EnvFile, [string[]]$lines)   # UTF-8 without BOM
Info "DATABASE_URL written (user $AppUser, port $Port)"

$env:PGPASSWORD = $appPw
$ver = & $psql -h localhost -p $Port -U $AppUser -d $DbName -t -A -v ON_ERROR_STOP=1 -c "SELECT postgis_full_version();"
Check-Exit "verification connection as $AppUser"
Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
Info "connected as $AppUser -> $($ver.Substring(0, [Math]::Min(60, $ver.Length)))..."

Write-Host "`n[setup_db] SUCCESS. PostgreSQL + PostGIS running on localhost:$Port" -ForegroundColor Green
Write-Host "Next: cd backend; py -3.11 -m venv .venv; .venv\Scripts\activate; pip install -r requirements.txt; pytest"
exit 0
