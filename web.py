from __future__ import annotations

import json
import threading
import urllib.request
import webbrowser
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from rag_core import answer, connect, ingest


ROOT = Path(__file__).resolve().parent
DATABASE = ROOT / "data" / "index.sqlite"
PAGE = ROOT / "web" / "index.html"
MODEL = "qwen2.5:3b"
OLLAMA = "http://127.0.0.1:11434"
PORT = 8765


def ollama_state() -> str:
    """ok - модель готова, no-model - Ollama запущена без модели, off - Ollama не запущена."""
    try:
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=1.5) as response:
            names = [item.get("name", "") for item in json.load(response).get("models", [])]
    except Exception:
        return "off"
    return "ok" if MODEL in names else "no-model"


def list_documents() -> list[dict]:
    if not DATABASE.exists():
        return []
    with closing(connect(DATABASE)) as connection:
        rows = connection.execute("SELECT source, COUNT(*) FROM chunks GROUP BY source ORDER BY source").fetchall()
    return [{"name": Path(source).stem.replace("_", " "), "chunks": count} for source, count in rows]


class Handler(BaseHTTPRequestHandler):
    def send_json(self, data: dict | list, status: int = 200) -> None:
        content = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        if self.path in {"/", "/index.html"}:
            content = PAGE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == "/api/status":
            self.send_json({"model": MODEL, "ollama": ollama_state(), "documents": list_documents()})
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/ask":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 30000:
                raise ValueError("Слишком длинный запрос")
            data = json.loads(self.rfile.read(length))
            question = str(data.get("question", "")).strip()
            if not question:
                raise ValueError("Напишите вопрос")
            history = data.get("history", [])
            if not isinstance(history, list):
                raise ValueError("Некорректная история диалога")
            response, matches = answer(question, DATABASE, model=MODEL, history=history, mode="ai")
            self.send_json({"answer": response, "sources": [{"name": Path(item["source"]).stem.replace("_", " "), "fragment": item["position"]} for item in matches]})
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, 400)
        except Exception:
            self.send_json({"error": "Не удалось получить ответ. Попробуйте ещё раз."}, 500)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    files, chunks = ingest(ROOT / "sample", DATABASE)
    print(f"Загружено {files} файлов и {chunks} фрагментов")
    url = f"http://127.0.0.1:{PORT}"
    print(f"Помощник открыт: {url}  (остановить: Ctrl+C)")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nСервер остановлен")
