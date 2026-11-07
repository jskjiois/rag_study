$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    py -3 -m venv .venv
}
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Python 3 not found. Install Python and try again.'
}

& $python -c 'import pypdf' 2>$null
if ($LASTEXITCODE -ne 0) {
    & $python -m pip install -r requirements.txt
}

$ollama = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
if (-not (Test-Path -LiteralPath $ollama)) {
    $command = Get-Command ollama -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw 'Ollama not found. Install it from ollama.com and try again.'
    }
    $ollama = $command.Source
}

try {
    $tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2
} catch {
    Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoExit', '-Command', "& '$ollama' serve") -WindowStyle Normal
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 1
        try {
            $tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2
            break
        } catch {}
    }
}
if ($null -eq $tags) {
    throw 'Ollama did not start. Check the new console window and try again.'
}

if (@($tags.models.name) -notcontains 'qwen2.5:3b') {
    & $ollama pull qwen2.5:3b
}

& $python demo.py
if ($LASTEXITCODE -ne 0) {
    throw 'Demo failed.'
}
& $python app.py chat --model qwen2.5:3b
