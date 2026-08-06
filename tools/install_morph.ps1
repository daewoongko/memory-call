[CmdletBinding()]
param(
    [string]$Root = $env:MEMORY_CALL_ROOT
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($Root)) {
    $projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
}
else {
    $projectRoot = [IO.Path]::GetFullPath($Root)
}

$facesRoot = Join-Path $projectRoot 'data\faces'
$sourceVideo = Join-Path $facesRoot 'morph.next.mp4'
$sourceMetadata = Join-Path $facesRoot 'morph.next.json'
$sourceQc = Join-Path $facesRoot 'morph.next.qc.png'
$targetVideo = Join-Path $facesRoot 'morph.mp4'
$targetMetadata = Join-Path $facesRoot 'morph.json'
$validator = Join-Path $projectRoot 'tools\validate_morph.py'
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'

foreach ($required in @($projectRoot, $facesRoot, $sourceVideo, $validator, $python)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required path does not exist: $required"
    }
}

Write-Host 'Validating staged RIFE morph...'
& $python -B $validator --strict
if ($LASTEXITCODE -ne 0) {
    throw "Staged morph validation failed with exit code $LASTEXITCODE."
}

foreach ($required in @($sourceMetadata, $sourceQc)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Validator did not create required artifact: $required"
    }
}

$metadata = Get-Content -LiteralPath $sourceMetadata -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $metadata.validation.passed) {
    throw 'Refusing to install a morph that did not pass validation.'
}

function Assert-RepositoryRelativePath {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $normalized = $Value.Replace('\', '/')
    if ([IO.Path]::IsPathRooted($Value) -or $normalized -eq '..' -or $normalized.StartsWith('../')) {
        throw "Metadata path must be repository-relative ($Label): $Value"
    }
}

if (-not $metadata.generator.model) {
    throw 'Validation metadata does not identify the RIFE model.'
}
$metadataPaths = @(
    [pscustomobject]@{ Value = [string]$metadata.video.path; Label = 'video.path' }
    [pscustomobject]@{ Value = [string]$metadata.video.validated_staging_path; Label = 'video.validated_staging_path' }
    [pscustomobject]@{ Value = [string]$metadata.generator.model.path; Label = 'generator.model.path' }
    [pscustomobject]@{ Value = [string]$metadata.source_manifest; Label = 'source_manifest' }
    [pscustomobject]@{ Value = [string]$metadata.validation.qc_contact_sheet; Label = 'validation.qc_contact_sheet' }
)
if ($metadata.validation.face_detector.model) {
    $metadataPaths += [pscustomobject]@{
        Value = [string]$metadata.validation.face_detector.model
        Label = 'validation.face_detector.model'
    }
}
foreach ($item in $metadata.source_sequence) {
    $metadataPaths += [pscustomobject]@{
        Value = [string]$item.path
        Label = "source_sequence[$($item.age)].path"
    }
}
foreach ($entry in $metadataPaths) {
    Assert-RepositoryRelativePath -Value $entry.Value -Label $entry.Label
}

if ([string]$metadata.video.path -ne 'data/faces/morph.mp4') {
    throw "Unexpected published video path in metadata: $($metadata.video.path)"
}
if ([string]$metadata.video.validated_staging_path -ne 'data/faces/morph.next.mp4') {
    throw "Unexpected staging video path in metadata: $($metadata.video.validated_staging_path)"
}
if ([string]$metadata.validation.qc_contact_sheet -ne 'data/faces/morph.next.qc.png') {
    throw "Unexpected QC path in metadata: $($metadata.validation.qc_contact_sheet)"
}

$sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourceVideo).Hash.ToLowerInvariant()
if ($sourceHash -ne [string]$metadata.video.sha256) {
    throw "Video hash does not match morph.next.json: $sourceHash"
}
if ([int64]$metadata.video.size_bytes -ne (Get-Item -LiteralPath $sourceVideo).Length) {
    throw 'Video size does not match morph.next.json.'
}
if ([int]$metadata.video.width -ne 768 -or [int]$metadata.video.height -ne 1024) {
    throw 'Unexpected output dimensions; expected 768x1024.'
}
if ([int]$metadata.video.decoded_frame_count -ne 852 -or [math]::Abs([double]$metadata.video.fps - 30.0) -gt 0.01) {
    throw 'Unexpected timeline; expected 852 frames at 30 fps.'
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmssfff'
$backupDir = Join-Path $facesRoot "_morph_backup\$stamp"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

function Install-Atomically {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Target,
        [Parameter(Mandatory = $true)][string]$Backup
    )

    $targetDirectory = [IO.Path]::GetDirectoryName($Target)
    $extension = [IO.Path]::GetExtension($Target)
    $temporary = Join-Path $targetDirectory ('.morph-installing-' + [guid]::NewGuid().ToString('N') + $extension)
    Copy-Item -LiteralPath $Source -Destination $temporary
    try {
        if (Test-Path -LiteralPath $Target -PathType Leaf) {
            [IO.File]::Replace($temporary, $Target, $Backup, $true)
        }
        else {
            [IO.File]::Move($temporary, $Target)
        }
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

$videoBackup = Join-Path $backupDir 'morph.mp4'
$metadataBackup = Join-Path $backupDir 'morph.json'
Install-Atomically -Source $sourceVideo -Target $targetVideo -Backup $videoBackup
Install-Atomically -Source $sourceMetadata -Target $targetMetadata -Backup $metadataBackup

$installedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $targetVideo).Hash.ToLowerInvariant()
if ($installedHash -ne $sourceHash) {
    throw "Installed video hash mismatch: $installedHash"
}

Write-Host 'Final RIFE morph installed successfully.'
Write-Host "Video: $targetVideo"
Write-Host "Metadata: $targetMetadata"
Write-Host "SHA256: $installedHash"
Write-Host "Backup: $backupDir"
Write-Host 'Timeline: age 8 -> 32 | 768x1024 | 30 fps | 852 frames | 28.4 seconds'
