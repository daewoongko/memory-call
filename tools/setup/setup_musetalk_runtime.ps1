[CmdletBinding()]
param(
    [string]$MuseTalkDir,
    [string]$PythonPath,
    [switch]$SkipPackages,
    [switch]$SkipModels,
    [switch]$SkipTrial
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $MuseTalkDir) {
    $MuseTalkDir = Join-Path (Split-Path -Parent $root) "Models\MuseTalk"
}
if (-not $PythonPath) {
    $PythonPath = Join-Path $root ".tools\python310\bin\python.exe"
}
$MuseTalkDir = [System.IO.Path]::GetFullPath($MuseTalkDir)
$PythonPath = [System.IO.Path]::GetFullPath($PythonPath)

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "MuseTalk Python 3.10 was not found: $PythonPath"
}
if (-not (Test-Path -LiteralPath (Join-Path $MuseTalkDir "scripts\inference.py") -PathType Leaf)) {
    throw "MuseTalk source checkout was not found: $MuseTalkDir"
}

$version = (& $PythonPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or $version -ne "3.10") {
    throw "MuseTalk requires Python 3.10; found $version at $PythonPath"
}

function Invoke-Python {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $PythonPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE"
    }
}

function Get-ModelFile {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string]$Filename,
        [Parameter(Mandatory = $true)][string]$LocalDirectory
    )

    $destination = Join-Path $LocalDirectory ($Filename -replace "/", "\")
    if ((Test-Path -LiteralPath $destination -PathType Leaf) -and
        (Get-Item -LiteralPath $destination).Length -gt 0) {
        Write-Host "Already present: $destination"
        return
    }

    New-Item -ItemType Directory -Force -Path $LocalDirectory | Out-Null
    Invoke-Python -c @"
from huggingface_hub import hf_hub_download
hf_hub_download(
    repo_id=r'''$Repository''',
    filename=r'''$Filename''',
    local_dir=r'''$LocalDirectory''',
)
"@

    if (-not (Test-Path -LiteralPath $destination -PathType Leaf) -or
        (Get-Item -LiteralPath $destination).Length -le 0) {
        throw "Model download did not create the required file: $destination"
    }
}

if (-not $SkipPackages) {
    Write-Host "Installing the isolated MuseTalk 1.5 runtime..."
    Invoke-Python -m pip install --upgrade pip
    Invoke-Python -m pip install torch==2.0.1 torchvision==0.15.2 torchaudio==2.0.2 --index-url https://download.pytorch.org/whl/cu118
    Invoke-Python -m pip install -r (Join-Path $MuseTalkDir "requirements.txt")
    Invoke-Python -m pip install --upgrade openmim
    Invoke-Python -m pip install https://download.openmmlab.com/mmcv/dist/cu118/torch2.0.0/mmcv-2.0.1-cp310-cp310-win_amd64.whl
    Invoke-Python -m mim install mmengine
    Invoke-Python -m mim install "mmdet==3.1.0"
    # MMPose 1.1.0 declares chumpy even though MuseTalk does not import it.
    # Chumpy cannot build in a modern isolated PEP 517 environment, so install
    # the runtime dependencies MuseTalk actually uses and then MMPose itself.
    Invoke-Python -m pip install json_tricks munkres "xtcocotools>=1.12"
    Invoke-Python -m pip install --no-deps "mmpose==1.1.0"
    Invoke-Python -c "import torch, cv2, mmcv, mmengine, mmdet, mmpose; assert torch.cuda.is_available(); print(torch.__version__, torch.cuda.get_device_name(0))"
}

if (-not $SkipModels) {
    Write-Host "Downloading the official MuseTalk 1.5 model set..."
    # Transformers 4.39.2 requires huggingface_hub < 1.0. Keep the version
    # pinned by MuseTalk while adding Xet support for the large UNet file.
    Invoke-Python -m pip install --no-deps "huggingface_hub==0.30.2" "hf-xet==1.6.0"

    $models = Join-Path $MuseTalkDir "models"
    New-Item -ItemType Directory -Force -Path $models | Out-Null
    # Download one exact path per call. Newer Hugging Face CLIs can ignore a
    # multi-file filter when positional filenames are also supplied, which
    # previously left several small but mandatory config files missing.
    Get-ModelFile "TMElyralab/MuseTalk" "musetalkV15/musetalk.json" $models
    Get-ModelFile "TMElyralab/MuseTalk" "musetalkV15/unet.pth" $models
    Get-ModelFile "stabilityai/sd-vae-ft-mse" "config.json" (Join-Path $models "sd-vae")
    Get-ModelFile "stabilityai/sd-vae-ft-mse" "diffusion_pytorch_model.bin" (Join-Path $models "sd-vae")
    Get-ModelFile "openai/whisper-tiny" "config.json" (Join-Path $models "whisper")
    Get-ModelFile "openai/whisper-tiny" "pytorch_model.bin" (Join-Path $models "whisper")
    Get-ModelFile "openai/whisper-tiny" "preprocessor_config.json" (Join-Path $models "whisper")
    Get-ModelFile "yzd-v/DWPose" "dw-ll_ucoco_384.pth" (Join-Path $models "dwpose")
    Get-ModelFile "ManyOtherFunctions/face-parse-bisent" "79999_iter.pth" (Join-Path $models "face-parse-bisent")
    Get-ModelFile "ManyOtherFunctions/face-parse-bisent" "resnet18-5c106cde.pth" (Join-Path $models "face-parse-bisent")

    $s3fd = Join-Path $MuseTalkDir "musetalk\utils\face_detection\detection\sfd\s3fd.pth"
    if (-not (Test-Path -LiteralPath $s3fd -PathType Leaf)) {
        $part = "$s3fd.part"
        Invoke-WebRequest -Uri "https://www.adrianbulat.com/downloads/python-fan/s3fd-619a316812.pth" -OutFile $part
        Move-Item -LiteralPath $part -Destination $s3fd -Force
    }

    $unet = Join-Path $models "musetalkV15\unet.pth"
    $expected = "7ebf6c98c181e20838e4c0054e96e944ac60d5d692cc01db42839fe11b787007"
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $unet).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        throw "MuseTalk 1.5 UNet checksum mismatch: $actual"
    }
}

if (-not $SkipTrial) {
    Write-Host "Running the isolated Korean lip-sync trial..."
    & (Join-Path $root ".venv\Scripts\python.exe") (Join-Path $PSScriptRoot "musetalk_trial.py") --musetalk-dir $MuseTalkDir --musetalk-python $PythonPath
    if ($LASTEXITCODE -ne 0) {
        throw "MuseTalk Korean trial failed with exit code $LASTEXITCODE"
    }
}
