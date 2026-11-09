$ErrorActionPreference = 'Continue'
Set-Location -LiteralPath $PSScriptRoot -ErrorAction Stop

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $launcher) {
        & $launcher.Source -3 -m venv .venv
    } else {
        $launcher = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $launcher) {
            throw 'Python 3 not found. Install Python and try again.'
        }
        & $launcher.Source -m venv .venv
    }
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not create the Python environment.'
    }
}
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Python 3 not found. Install Python and try again.'
}

& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    throw 'Could not install Python packages.'
}

$ollama = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
if (-not (Test-Path -LiteralPath $ollama)) {
    $command = Get-Command ollama -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw 'Ollama not found. Install it from ollama.com and try again.'
    }
    $ollama = $command.Source
}

$tags = $null
try {
    $tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 -ErrorAction Stop
} catch {
    Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoExit', '-Command', "& '$ollama' serve") -WindowStyle Normal -ErrorAction Stop
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 1
        try {
            $tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 -ErrorAction Stop
            break
        } catch {}
    }
}
if ($null -eq $tags) {
    throw 'Ollama did not start. Check the new console window and try again.'
}

if (@($tags.models.name) -notcontains 'qwen2.5:3b') {
    & $ollama pull qwen2.5:3b
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not download the Ollama model.'
    }
}

& $python demo.py
if ($LASTEXITCODE -ne 0) {
    throw 'Demo failed.'
}
& $python app.py chat --model qwen2.5:3b
if ($LASTEXITCODE -ne 0) {
    throw 'Chat failed.'
}
