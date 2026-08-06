[CmdletBinding()]
param(
    [switch]$Force,
    [ValidatePattern('^[A-Fa-f0-9]{64}$')]
    [string]$ExpectedSha256
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$toolDirectory = Join-Path $repoRoot '.tools'
$target = Join-Path $toolDirectory 'cloudflared.exe'
[IO.Directory]::CreateDirectory($toolDirectory) | Out-Null

$releaseUri = 'https://api.github.com/repos/cloudflare/cloudflared/releases/latest'
$headers = @{
    Accept = 'application/vnd.github+json'
    'User-Agent' = 'memory-call-cloudflared-installer/1.0'
    'X-GitHub-Api-Version' = '2022-11-28'
}
$release = Invoke-RestMethod -Uri $releaseUri -Headers $headers
$asset = @($release.assets) | Where-Object { $_.name -eq 'cloudflared-windows-amd64.exe' } | Select-Object -First 1
if ($null -eq $asset) {
    throw 'The official cloudflared Windows amd64 release asset was not found.'
}

$expected = $ExpectedSha256
if ([string]::IsNullOrWhiteSpace($expected) -and $asset.PSObject.Properties.Name -contains 'digest') {
    $digest = [string]$asset.digest
    if ($digest -match '^sha256:([A-Fa-f0-9]{64})$') {
        $expected = $Matches[1]
    }
}
if ([string]::IsNullOrWhiteSpace($expected)) {
    throw 'GitHub did not provide an SHA-256 digest. Re-run with -ExpectedSha256 after verifying the official release checksum.'
}

if ((Test-Path -LiteralPath $target -PathType Leaf) -and -not $Force) {
    $existingHash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
    if (-not $existingHash.Equals($expected, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Existing cloudflared does not match the current official release digest. Re-run with -Force to replace it.'
    }
    & $target --version
    if ($LASTEXITCODE -ne 0) {
        throw "Existing cloudflared failed validation: $target"
    }
    Write-Host "Verified cloudflared is already installed: $target"
    exit 0
}

$temporary = Join-Path $toolDirectory ('.cloudflared-download-{0}.exe' -f [Guid]::NewGuid().ToString('N'))
try {
    Invoke-WebRequest -Uri ([string]$asset.browser_download_url) -Headers $headers -OutFile $temporary -UseBasicParsing
    $actual = (Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash
    if (-not $actual.Equals($expected, [StringComparison]::OrdinalIgnoreCase)) {
        throw "cloudflared SHA-256 verification failed. Expected $expected but received $actual."
    }

    & $temporary --version
    if ($LASTEXITCODE -ne 0) {
        throw 'Downloaded cloudflared executable failed its version check.'
    }

    if (Test-Path -LiteralPath $target -PathType Leaf) {
        $backup = Join-Path $toolDirectory ('cloudflared-{0}.bak.exe' -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
        [IO.File]::Replace($temporary, $target, $backup, $true)
        Write-Host "Previous executable preserved at: $backup"
    }
    else {
        [IO.File]::Move($temporary, $target)
    }
    Write-Host "Verified cloudflared installed: $target"
}
finally {
    if (Test-Path -LiteralPath $temporary -PathType Leaf) {
        Remove-Item -LiteralPath $temporary -Force
    }
}
