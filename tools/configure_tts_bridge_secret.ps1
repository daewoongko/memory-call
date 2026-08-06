[CmdletBinding()]
param(
    [string]$Token,
    [switch]$CopyToClipboard
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$envPath = Join-Path $repoRoot '.env'
$examplePath = Join-Path $repoRoot '.env.example'

if ([string]::IsNullOrWhiteSpace($Token)) {
    $bytes = [byte[]]::new(48)
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    $Token = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}
$Token = $Token.Trim()
if ($Token.Length -lt 32 -or $Token -match '[\r\n\s]') {
    throw 'TTS_BRIDGE_TOKEN must be at least 32 characters and contain no whitespace.'
}

if (Test-Path -LiteralPath $envPath -PathType Leaf) {
    $lines = [Collections.Generic.List[string]]::new()
    foreach ($line in [IO.File]::ReadAllLines($envPath)) {
        $lines.Add($line)
    }
}
elseif (Test-Path -LiteralPath $examplePath -PathType Leaf) {
    $lines = [Collections.Generic.List[string]]::new()
    foreach ($line in [IO.File]::ReadAllLines($examplePath)) {
        $lines.Add($line)
    }
}
else {
    $lines = [Collections.Generic.List[string]]::new()
}

$replacement = "TTS_BRIDGE_TOKEN=$Token"
$found = $false
for ($index = 0; $index -lt $lines.Count; $index += 1) {
    if ($lines[$index] -match '^\s*TTS_BRIDGE_TOKEN\s*=') {
        $lines[$index] = $replacement
        $found = $true
        break
    }
}
if (-not $found) {
    if ($lines.Count -gt 0 -and $lines[$lines.Count - 1] -ne '') {
        $lines.Add('')
    }
    $lines.Add('# Shared only with the Render TTS bridge secret; never commit this file.')
    $lines.Add($replacement)
}

$utf8WithoutBom = [Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllLines($envPath, $lines, $utf8WithoutBom)

if ($CopyToClipboard) {
    if (Get-Command Set-Clipboard -ErrorAction SilentlyContinue) {
        Set-Clipboard -Value $Token
        Write-Host 'TTS bridge secret saved to .env and copied to the clipboard (value hidden).'
    }
    else {
        throw 'The secret was saved to .env, but Set-Clipboard is unavailable.'
    }
}
else {
    Write-Host 'TTS bridge secret saved to .env (value hidden).'
}
Write-Host 'Set the same value as Render environment variable TTS_BRIDGE_TOKEN.'
