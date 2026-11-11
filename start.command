#!/bin/bash
set -e

cd -- "$(dirname -- "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

case "${1:-chat}" in
    chat|demo) entry=console.py ;;
    web) entry=web.py ;;
    *) echo "Использование: $0 [chat|demo|web]" >&2; exit 2 ;;
esac

if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))'; then
    echo "Установите Python 3.9 или новее." >&2
    exit 1
fi

ollama=$(command -v ollama || true)
if [[ -z "$ollama" ]]; then
    ollama=/Applications/Ollama.app/Contents/Resources/ollama
fi
if [[ ! -x "$ollama" ]]; then
    echo "Установите Ollama в папку «Программы»." >&2
    exit 1
fi

python=.venv-mac/bin/python
if [[ ! -x "$python" ]]; then
    python3 -m venv .venv-mac
fi
"$python" -m pip install -r requirements.txt

ollama_ready() {
    curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1
}

if ! ollama_ready; then
    "$ollama" serve >.venv-mac/ollama.log 2>&1 &
    ollama_pid=$!
    trap 'kill "$ollama_pid" 2>/dev/null || true' EXIT
    for ((attempt=0; attempt<20; attempt++)); do
        ollama_ready && break
        sleep 1
    done
    if ! ollama_ready; then
        echo "Ollama не запустилась. Журнал: .venv-mac/ollama.log" >&2
        exit 1
    fi
fi

if ! "$ollama" show qwen2.5:3b >/dev/null 2>&1; then
    "$ollama" pull qwen2.5:3b
fi

if [[ "${1:-chat}" == demo ]]; then
    "$python" demo.py
fi
"$python" "$entry"
