from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from rag_core import answer, ingest


ROOT = Path(__file__).resolve().parent
DATABASE = ROOT / "data" / "index.sqlite"
PAGE = ROOT / "web" / "index.html"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/":
            self.send_error(404)
            return
        content = PAGE.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        if self.path != "/ask":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 10000:
                raise ValueError("Слишком длинный вопрос")
            data = json.loads(self.rfile.read(length))
            question = str(data.get("question", "")).strip()
            if not question:
                raise ValueError("Напишите вопрос")
            response, matches = answer(question, DATABASE, model="qwen2.5:3b")
            result = {"answer": response, "sources": [{"name": Path(item["source"]).name, "fragment": item["position"]} for item in matches]}
            status = 200
        except (ValueError, json.JSONDecodeError) as exc:
            result = {"error": str(exc)}
            status = 400
        except Exception:
            result = {"error": "Не удалось получить ответ. Попробуйте ещё раз."}
            status = 500
        content = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


if __name__ == "__main__":
    files, chunks = ingest(ROOT / "sample", DATABASE)
    print(f"Загружено {files} файлов и {chunks} фрагментов")
    print("Откройте в браузере http://127.0.0.1:8765")
    try:
        ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nСервер остановлен")
