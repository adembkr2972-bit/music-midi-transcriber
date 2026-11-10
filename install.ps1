$ErrorActionPreference = "Stop"

$environmentPath = Join-Path $PSScriptRoot ".venv"
$appPython = Join-Path $environmentPath "Scripts\python.exe"
$requirementsPath = Join-Path $PSScriptRoot "requirements.txt"

if (-not (Test-Path $appPython)) {
    & py -3.11 -m venv $environmentPath
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the Python 3.11 environment."
    }
}

& $appPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Could not upgrade pip."
}

& $appPython -m pip install -r $requirementsPath
if ($LASTEXITCODE -ne 0) {
    throw "Could not install the app dependencies."
}

# Basic Pitch 0.4.0 pulls in TensorFlow on Python 3.11. Use the ONNX runtime
# listed above instead, avoiding its old TensorFlow/protobuf dependency conflict.
& $appPython -m pip install --no-deps "basic-pitch==0.4.0"
if ($LASTEXITCODE -ne 0) {
    throw "Could not install Basic Pitch."
}

if (-not (Get-Command ffmpeg.exe -ErrorAction SilentlyContinue)) {
    Write-Warning "Demucs audio decoding also needs the FFmpeg shared build on PATH. Install it with: winget install --id BtbN.FFmpeg.LGPL.Shared.8.1 --exact"
}

Write-Host "Setup complete. Start the app with:"
Write-Host ".\.venv\Scripts\python.exe -m streamlit run streamlit_app.py"
