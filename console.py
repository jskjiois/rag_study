from __future__ import annotations

import itertools
import json
import os
import re
import shutil
import sys
import textwrap
import threading
import time
import urllib.request
from contextlib import closing
from pathlib import Path

from rag_core import answer, connect, exact_string_concat_code, has_relevant_matches, ingest, search

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
if os.name == "nt":
    os.system("")  # включает ANSI-цвета в консоли Windows

ROOT = Path(__file__).resolve().parent
DATABASE = ROOT / "data" / "index.sqlite"
SAMPLE = ROOT / "sample"
MODEL = "qwen2.5:3b"
OLLAMA = "http://127.0.0.1:11434"
EXAMPLES = ["Что такое алгоритм?", "Что делает append в Python?", "Как перевести число в двоичную систему?", "Чем цикл for отличается от while?"]

# Спокойная палитра: шалфейный зелёный, тёплый кремовый, янтарь для источников
ACCENT, TEXT, MUTED, AMBER, OK, BAD, ME = "134;199;166", "232;226;212", "138;154;146", "217;178;111", "127;199;154", "217;138;122", "158;197;217"
RESET = "\x1b[0m"
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def paint(text: str, color: str, bold: bool = False) -> str:
    return f"\x1b[{'1;' if bold else ''}38;2;{color}m{text}{RESET}"


def width() -> int:
    return max(50, min(shutil.get_terminal_size((100, 30)).columns, 100))


def visible(text: str) -> int:
    return len(ANSI.sub("", text))


def panel(lines: list[str], title: str = "", color: str = ACCENT) -> None:
    w = width()
    top = "╭─ " + title + " " if title else "╭"
    print(paint(top + "─" * (w - len(top) - 1) + "╮", color))
    for line in lines:
        print(paint("│", color) + " " + line + " " * (w - 4 - visible(line)) + " " + paint("│", color))
    print(paint("╰" + "─" * (w - 2) + "╯", color))


def center(text: str) -> str:
    return " " * max(0, (width() - 4 - visible(text)) // 2) + text


def inline(line: str) -> str:
    line = re.sub(r"\*\*([^*]+)\*\*", lambda m: paint(m.group(1), TEXT, True), line)
    line = re.sub(r"`([^`]+)`", lambda m: paint(m.group(1), AMBER), line)
    return line


def render(markdown: str) -> list[str]:
    """Очень простой разбор: абзацы, списки, блоки кода."""
    inner = width() - 4
    out: list[str] = []
    for index, part in enumerate(markdown.split("```")):
        if index % 2:
            code = re.sub(r"^[\w+-]*\n", "", part).strip("\n")
            out.extend(code.split("\n"))
            continue
        for paragraph in re.split(r"\n\s*\n", part.strip()):
            for row in paragraph.split("\n"):
                row = re.sub(r"^#+\s*", "", row.strip())
                if not row:
                    continue
                bullet = re.match(r"^([-*•]|\d+[.)])\s+(.*)", row)
                if bullet:
                    mark = "•" if bullet.group(1) in "-*•" else bullet.group(1)
                    wrapped = textwrap.wrap(bullet.group(2), inner - 3) or [""]
                    for n, w_ in enumerate(wrapped):
                        out.append((paint(mark, ACCENT) if n == 0 else " ") + " " + inline(w_))
                else:
                    out.extend(inline(w_) for w_ in textwrap.wrap(row, inner) or [""])
            out.append("")
        if out and out[-1] == "":
            out.pop()
            out.append("")
    while out and out[-1] == "":
        out.pop()
    return out


def ollama_state() -> str:
    try:
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=1.5) as response:
            names = [item.get("name", "") for item in json.load(response).get("models", [])]
    except Exception:
        return "off"
    return "ok" if MODEL in names else "no-model"


def status_line(state: str) -> str:
    if state == "ok":
        return paint("●", OK) + paint(f" ИИ {MODEL} готов", MUTED)
    if state == "no-model":
        return paint("●", BAD) + paint(f" нет модели, выполни: ollama pull {MODEL}", MUTED)
    return paint("●", BAD) + paint(" Ollama не запущена — ответы ИИ недоступны", MUTED)


def documents() -> list[tuple[str, int]]:
    if not DATABASE.exists():
        return []
    with closing(connect(DATABASE)) as connection:
        rows = connection.execute("SELECT source, COUNT(*) FROM chunks GROUP BY source ORDER BY source").fetchall()
    return [(Path(source).stem.replace("_", " "), count) for source, count in rows]


def header(state: str, mode: str) -> None:
    print("\x1b[2J\x1b[H", end="")
    mode_names = {
        "auto": "режим: библиотека → ИИ Qwen (автоматически)",
        "ai": "режим: прямой диалог с ИИ Qwen",
        "rag": "режим: ответы с приоритетом библиотеки",
    }
    mode_name = mode_names.get(mode, mode_names["auto"])
    panel(["", center(paint("Локальный ИИ-помощник", ACCENT, True)), center(paint(mode_name, MUTED)), center(status_line(state)), ""])
    print(paint("  Команды: /help  /auto  /docs  /ai  /rag  /new  /exit", MUTED) + "\n")


def welcome() -> None:
    print(paint("  Привет! Я работаю на Qwen 2.5 3B. Можешь задавать любые вопросы.", TEXT))
    print(paint("  Сначала проверяю библиотеку проекта; если ответа нет — автоматически обращаюсь к Qwen.", MUTED))
    for example in EXAMPLES:
        print(paint("    › " + example, AMBER))
    print()


def spinner(stop: threading.Event, label: str) -> None:
    for frame in itertools.cycle("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"):
        if stop.is_set():
            break
        print(f"\r  {paint(frame, ACCENT)} {paint(label, MUTED)}", end="", flush=True)
        time.sleep(0.08)
    print("\r" + " " * (visible(label) + 6) + "\r", end="", flush=True)


def with_spinner(label: str, func, *args, **kwargs):
    stop = threading.Event()
    thread = threading.Thread(target=spinner, args=(stop, label), daemon=True)
    thread.start()
    try:
        return func(*args, **kwargs)
    finally:
        stop.set()
        thread.join()


def read_message() -> str:
    """Окно ввода сообщения: рамка с приглашением внутри."""
    w = width()
    print(paint("╭" + "─" * (w - 2) + "╮", ACCENT))
    try:
        return input(paint("│ ", ACCENT) + paint("❯ ", ACCENT, True)).strip()
    finally:
        print(paint("╰" + "─" * (w - 2) + "╯", ACCENT))


def show_answer(question: str, history: list[dict], mode: str) -> str | None:
    print(paint("Ты", ME, True))
    for row in textwrap.wrap(question, width() - 2):
        print("  " + paint(row, TEXT))
    print()

    exact_code = exact_string_concat_code(question)
    if exact_code is not None:
        print(paint("  [ТОЧНОЕ ВЫПОЛНЕНИЕ] Исходные слова сохранены без изменений.", OK))
        print(paint("Точное соединение строк · Python", ACCENT, True))
        print(exact_code)
        print()
        return exact_code

    route = mode
    matches: list[dict] = []
    if mode in {"auto", "rag"}:
        try:
            matches = with_spinner("Проверяю библиотеку проекта…", search, question, DATABASE, 3)
        except Exception as exc:
            panel([paint(f"Не удалось выполнить поиск по библиотеке: {exc}", BAD)], "Ошибка поиска", BAD)
            return None

        matches = [item for item in matches if item]
        relevant = has_relevant_matches(question, matches)
        if mode == "auto" and not relevant:
            route = "ai"
            print(paint("  [БИБЛИОТЕКА] Подходящая информация не найдена.", AMBER, True))
            print(paint("  [ИИ QWEN] Переключаюсь на Qwen 2.5 3B и ищу ответ в знаниях модели…", ACCENT))
            print()
        elif relevant:
            route = "rag"
            print(paint("  [БИБЛИОТЕКА] Найдены подходящие материалы. Qwen формирует ответ на их основе…", OK))
            print()
        else:
            route = "ai"
            print(paint("  [БИБЛИОТЕКА] Подходящая информация не найдена.", AMBER, True))
            print(paint("  [ИИ QWEN] Даю ответ на основе знаний модели…", ACCENT))
            print()
    elif mode == "ai":
        route = "ai"
        print(paint("  [ИИ QWEN] Отвечаю напрямую, без поиска по библиотеке…", ACCENT))
        print()

    label = "Qwen отвечает по библиотеке…" if route == "rag" else "Qwen ищет ответ в своих знаниях…"
    try:
        response, used_matches = with_spinner(
            label, answer, question, DATABASE, 3, MODEL, OLLAMA, history, route,
            matches_override=matches if route == "rag" else None,
        )
    except Exception as exc:
        panel([paint(f"Не удалось получить ответ: {exc}", BAD)], "Ошибка", BAD)
        return None
    lines = render(response)
    if used_matches:
        lines.append("")
        lines.append(paint("Источники из библиотеки:", MUTED))
        for number, match in enumerate(used_matches, 1):
            name = Path(match["source"]).stem.replace("_", " ")
            lines.append(paint(f"  [{number}] {name}, фрагмент {match['position']}", AMBER))
    elif route == "ai":
        lines.append("")
        lines.append(paint("Источник ответа: знания модели Qwen 2.5 3B; подходящие фрагменты библиотеки не найдены.", MUTED))
    print(paint("Qwen 2.5 3B", ACCENT, True))
    for line in lines:
        print(line)
    print()
    return response


def main() -> int:
    try:
        with_spinner("Загружаю конспекты…", ingest, SAMPLE, DATABASE)
    except (ValueError, FileNotFoundError, OSError) as exc:
        print(paint(f"Ошибка загрузки конспектов: {exc}", BAD))
    state = ollama_state()
    mode = "auto"
    history: list[dict] = []
    header(state, mode)
    welcome()
    while True:
        try:
            message = read_message()
        except (EOFError, KeyboardInterrupt):
            break
        print()
        if not message:
            continue
        command = message.lower()
        if command in {"/exit", "/quit", "выход", "exit", "quit"}:
            break
        if command == "/help":
            panel([
                paint("/auto", ACCENT) + "  сначала библиотека, при отсутствии ответа — автоматический переход к Qwen",
                paint("/ai", ACCENT) + "    прямой диалог с Qwen без поиска по библиотеке",
                paint("/rag", ACCENT) + "   искать в библиотеке и передавать найденное Qwen",
                paint("/docs", ACCENT) + "  список загруженных материалов",
                paint("/new", ACCENT) + "   очистить историю и экран",
                paint("/exit", ACCENT) + "  выйти (или Ctrl+C)",
            ], "Команды", MUTED)
        elif command == "/docs":
            rows = documents()
            panel([paint(name, TEXT) + paint(f"  ({count} фр.)", MUTED) for name, count in rows] or [paint("База пуста", MUTED)], f"Конспекты ({len(rows)})", MUTED)
        elif command in {"/auto", "/ai", "/rag"}:
            mode = {"/auto": "auto", "/ai": "ai", "/rag": "rag"}[command]
            header(state, mode)
            print(paint("  Режим переключён. История разговора сохранена.", OK) + "\n")
            continue
        elif command == "/new":
            history.clear()
            state = ollama_state()
            header(state, mode)
            welcome()
            continue
        else:
            response = show_answer(message, history, mode)
            if response is not None:
                history.append({"role": "user", "content": message})
                history.append({"role": "assistant", "content": response})
                history[:] = history[-12:]
            continue
        print()
    print(paint("\n  До встречи! Удачной учёбы.", ACCENT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
