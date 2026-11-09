from __future__ import annotations

import argparse
import sys
from contextlib import closing
from pathlib import Path

from rag_core import answer, connect, ingest


def show_answer(question: str, database: Path, top_k: int, model: str | None, url: str) -> None:
    response, matches = answer(question, database, top_k, model, url)
    print(response)
    if matches:
        print("\nИсточники:")
        for number, match in enumerate(matches, 1):
            print(f"[{number}] {Path(match['source']).name}, фрагмент {match['position']}")


def main() -> int:
    if len(sys.argv) == 1:
        print('Для первого запуска открой терминал в папке проекта и выполни .\\start.cmd')
        return 0

    parser = argparse.ArgumentParser(description="Локальный помощник по учебным материалам")
    parser.add_argument("--db", type=Path, default=Path("data/index.sqlite"), help="Путь к индексу SQLite")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("ingest", help="Загрузить документ или папку")
    add.add_argument("source", type=Path)
    add.add_argument("--size", type=int, default=120)
    add.add_argument("--overlap", type=int, default=25)
    ask = commands.add_parser("ask", help="Найти ответ на вопрос")
    ask.add_argument("question")
    ask.add_argument("--top-k", type=int, default=3)
    ask.add_argument("--model", help="Модель Ollama, например qwen2.5:3b")
    ask.add_argument("--url", default="http://127.0.0.1:11434")
    chat = commands.add_parser("chat", help="Задавать вопросы до команды выход")
    chat.add_argument("--top-k", type=int, default=3)
    chat.add_argument("--model", default="qwen2.5:3b")
    chat.add_argument("--url", default="http://127.0.0.1:11434")
    commands.add_parser("list", help="Показать загруженные документы")
    args = parser.parse_args()
    try:
        if args.command == "ingest":
            files, chunks = ingest(args.source, args.db, args.size, args.overlap)
            print(f"Загружено документов: {files}; фрагментов: {chunks}")
        elif args.command == "ask":
            show_answer(args.question, args.db, args.top_k, args.model, args.url)
        elif args.command == "chat":
            print("Задавай вопросы по информатике и Python. Для завершения напиши: выход")
            while True:
                try:
                    question = input("\nВопрос: ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\nРабота завершена.")
                    break
                if question.lower() in {"выход", "exit", "quit"}:
                    print("Работа завершена.")
                    break
                if question:
                    show_answer(question, args.db, args.top_k, args.model, args.url)
        else:
            if not args.db.exists():
                print("Индекс пока пуст")
            else:
                with closing(connect(args.db)) as connection:
                    rows = connection.execute("SELECT source, COUNT(*) FROM chunks GROUP BY source ORDER BY source").fetchall()
                for source, count in rows:
                    print(f"{source} ({count} фрагментов)")
                if not rows:
                    print("Индекс пока пуст")
    except (ValueError, FileNotFoundError, RuntimeError, OSError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
