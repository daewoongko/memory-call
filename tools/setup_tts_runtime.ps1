[CmdletBinding()]
param(
    [string]$PythonPath,
    [string]$TargetPath,
    [switch]$InstallPython,
    [switch]$SkipPackages
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$requirements = Join-Path $repoRoot 'requirements-tts.txt'
if (-not (Test-Path -LiteralPath $requirements -PathType Leaf)) {
    throw "TTS requirements were not found: $requirements"
}

function Test-Python311([string]$Candidate) {
    try {
        if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf -ErrorAction Stop)) {
            return $false
        }
    }
    catch [UnauthorizedAccessException] {
        return $false
    }
    try {
        & $Candidate -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" 2>$null
    }
    catch [UnauthorizedAccessException] {
        return $false
    }
    return $LASTEXITCODE -eq 0
}

function Find-Python311 {
    if (-not [string]::IsNullOrWhiteSpace($PythonPath)) {
        $explicit = [IO.Path]::GetFullPath($PythonPath)
        if (-not (Test-Python311 $explicit)) {
            throw "-PythonPath must point to a working Python 3.11 executable: $explicit"
        }
        return $explicit
    }

    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($null -ne $launcher) {
        $resolved = (& $launcher.Source -3.11 -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1)
        if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($resolved)) {
            $resolved = [IO.Path]::GetFullPath($resolved.Trim())
            if (Test-Python311 $resolved) {
                return $resolved
            }
        }
    }

    $known = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'
    if (Test-Python311 $known) {
        return [IO.Path]::GetFullPath($known)
    }
    return $null
}

function Install-PinnedPython311 {
    # Python 3.11.9 is the exact base interpreter recorded in the existing
    # .venv-tts/pyvenv.cfg. Restoring it usually revives the large CUDA env
    # without downloading the model stack again.
    $version = '3.11.9'
    $installerUri = "https://www.python.org/ftp/python/$version/python-$version-amd64.exe"
    $expectedLength = 26216840
    $expectedMd5 = 'e8dcd502e34932eebcaf1be056d5cbcd'
    $temporary = Join-Path ([IO.Path]::GetTempPath()) ("python-$version-{0}.exe" -f [Guid]::NewGuid().ToString('N'))
    $installDirectory = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311'

    try {
        Write-Host "Downloading signed Python $version installer from python.org..."
        Invoke-WebRequest -Uri $installerUri -OutFile $temporary -UseBasicParsing

        $download = Get-Item -LiteralPath $temporary
        if ($download.Length -ne $expectedLength) {
            throw "Python installer size verification failed. Expected $expectedLength but received $($download.Length)."
        }
        $actualMd5 = (Get-FileHash -LiteralPath $temporary -Algorithm MD5).Hash
        if (-not $actualMd5.Equals($expectedMd5, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Python installer checksum verification failed.'
        }
        $signature = Get-AuthenticodeSignature -LiteralPath $temporary
        if (
            $signature.Status -ne [Management.Automation.SignatureStatus]::Valid -or
            $null -eq $signature.SignerCertificate -or
            $signature.SignerCertificate.Subject -notmatch 'Python Software Foundation'
        ) {
            throw "Python installer Authenticode verification failed: $($signature.Status)"
        }

        Write-Host "Installing Python $version for the current Windows user..."
        $arguments = @(
            '/quiet',
            'InstallAllUsers=0',
            ('TargetDir="{0}"' -f $installDirectory),
            'PrependPath=0',
            'Include_launcher=1',
            'Include_test=0',
            'Shortcuts=0'
        )
        $process = Start-Process -FilePath $temporary -ArgumentList $arguments -Wait -PassThru
        if ($process.ExitCode -ne 0) {
            throw "Python 3.11 installation failed with exit code $($process.ExitCode)."
        }
    }
    finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }

    $installed = Join-Path $installDirectory 'python.exe'
    if (-not (Test-Python311 $installed)) {
        throw "Python 3.11 installation completed but its interpreter is not runnable: $installed"
    }
    return [IO.Path]::GetFullPath($installed)
}

function Test-TtsRuntime([string]$Candidate) {
    if (-not (Test-Python311 $Candidate)) {
        return $false
    }
    # Windows PowerShell 5.1 can promote harmless native stderr warnings to a
    # terminating NativeCommandError when ErrorActionPreference is Stop.
    $previousErrorAction = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $null = & $Candidate -W ignore -c "import fastapi, librosa, soundfile, torch, uvicorn; from chatterbox.mtl_tts import ChatterboxMultilingualTTS; raise SystemExit(0 if torch.cuda.is_available() else 1)" 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
    return $exitCode -eq 0
}

$sourcePython = Find-Python311
if ($null -eq $sourcePython -and $InstallPython) {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($null -ne $winget) {
        & $winget.Source install --exact --id Python.Python.3.11 --source winget --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) {
            throw "Python 3.11 installation failed with exit code $LASTEXITCODE."
        }
        $sourcePython = Find-Python311
    }
    if ($null -eq $sourcePython) {
        $sourcePython = Install-PinnedPython311
    }
}
if ($null -eq $sourcePython) {
    throw 'A working Python 3.11 installation was not found. Re-run this script with -InstallPython. The existing .venv-tts will not be deleted.'
}

$primary = Join-Path $repoRoot '.venv-tts'
$primaryPython = Join-Path $primary 'Scripts\python.exe'
$targetExplicit = -not [string]::IsNullOrWhiteSpace($TargetPath)

# Installing the same 3.11.9 base often makes the existing multi-gigabyte CUDA
# environment runnable again. Prefer it unless an explicit target was supplied.
if (-not $targetExplicit -and (Test-Python311 $primaryPython)) {
    $target = $primary
    $targetPython = $primaryPython
    Write-Host "Reusing the repaired existing TTS environment: $target"
}
else {
    if (-not $targetExplicit) {
        $TargetPath = Join-Path $repoRoot '.venv-tts-recovered'
    }
    $target = [IO.Path]::GetFullPath($TargetPath)
    $repoPrefix = $repoRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (-not $target.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "The recovery environment must stay inside the repository: $repoRoot"
    }

    $targetPython = Join-Path $target 'Scripts\python.exe'
    if ((Test-Path -LiteralPath $target) -and -not (Test-Python311 $targetPython)) {
        $target = Join-Path $repoRoot ('.venv-tts-recovered-{0}' -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
        $targetPython = Join-Path $target 'Scripts\python.exe'
        Write-Warning "The requested target exists but is not healthy. It is preserved; using $target instead."
    }

    if (-not (Test-Python311 $targetPython)) {
        Write-Host "Creating a separate Python 3.11 TTS environment: $target"
        & $sourcePython -m venv $target
        if ($LASTEXITCODE -ne 0 -or -not (Test-Python311 $targetPython)) {
            throw 'Python 3.11 virtual-environment creation failed.'
        }
    }
    else {
        Write-Host "Reusing healthy Python 3.11 TTS environment: $target"
    }
}

if (-not $SkipPackages) {
    & $targetPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }
    & $targetPython -m pip install -r $requirements
    if ($LASTEXITCODE -ne 0) { throw 'TTS dependency installation failed.' }
}

if (-not (Test-TtsRuntime $targetPython)) {
    throw 'TTS runtime validation failed. Confirm the packages are installed and the NVIDIA CUDA GPU is available. The environment was preserved for diagnosis.'
}

& $targetPython -c "import torch; print('TTS runtime verified:', torch.__version__, torch.cuda.get_device_name(0))"
if ($LASTEXITCODE -ne 0) {
    throw 'TTS runtime validation output failed.'
}

Write-Host "TTS Python ready: $targetPython"
if (-not $targetPython.Equals($primaryPython, [StringComparison]::OrdinalIgnoreCase)) {
    Write-Host 'Use this process-local setting before starting the bridge:'
    Write-Host ('$env:TTS_PYTHON_PATH = ''{0}''' -f $targetPython)
}
Write-Host 'The original .venv-tts was not deleted.'
