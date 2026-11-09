from __future__ import annotations

import json
import math
import re
import sqlite3
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from contextlib import closing
from pathlib import Path
from xml.etree import ElementTree


WORD = re.compile(r"[\wёЁ]+", re.UNICODE)
SUPPORTED = {".txt", ".md", ".docx", ".pdf"}
ENDINGS = ("ующими", "ующему", "ующего", "ующую", "ировать", "ировать", "иями", "ями", "ами", "ого", "ыми", "ими", "овать", "ешь", "ают", "яют", "ует", "уют", "юют", "ую", "юю", "ого", "ому", "ыми", "ими", "иях", "ах", "ях", "ам", "ям", "ов", "ев", "ый", "ий", "ая", "ое", "ые", "ых", "ой", "ей", "ом", "ем", "ую", "юю", "а", "я", "ы", "и", "е", "у", "ю", "ь")


def normalize(word: str) -> str:
    word = word.lower()
    if not re.fullmatch(r"[а-яё]+", word):
        return word
    for ending in ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            return word[:-len(ending)]
    return word


STOPWORDS = {normalize(word) for word in {"а", "в", "во", "и", "или", "на", "по", "с", "со", "у", "из", "за", "для", "это", "что", "как", "какой", "какая", "какие", "такое", "зачем", "почему", "можно", "нужно", "ли", "делать", "работать", "python", "питон", "the", "is", "an"}}


def tokenize(text: str) -> list[str]:
    return [normalize(word) for word in WORD.findall(text)]


def read_document(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8-sig")
    if suffix == ".docx":
        with zipfile.ZipFile(path) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs = []
        for paragraph in root.findall(".//w:p", namespace):
            value = "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace))
            if value.strip():
                paragraphs.append(value)
        return "\n".join(paragraphs)
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("Для PDF установите зависимости: pip install -r requirements.txt") from exc
        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    raise ValueError(f"Неподдерживаемый формат: {path.suffix}")


def split_text(text: str, size: int = 120, overlap: int = 25) -> list[str]:
    if size < 1 or overlap < 0 or overlap >= size:
        raise ValueError("Размер фрагмента должен быть больше перекрытия")
    words = text.split()
    chunks = []
    for start in range(0, len(words), size - overlap):
        chunks.append(" ".join(words[start:start + size]))
        if start + size >= len(words):
            break
    return chunks


def collect_files(source: Path) -> list[Path]:
    if source.is_file():
        if source.suffix.lower() not in SUPPORTED:
            raise ValueError(f"Неподдерживаемый формат: {source.suffix}")
        return [source]
    if source.is_dir():
        return sorted(path for path in source.rglob("*") if path.is_file() and path.suffix.lower() in SUPPORTED)
    raise FileNotFoundError(source)


def connect(database: Path) -> sqlite3.Connection:
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY, source TEXT NOT NULL, position INTEGER NOT NULL, text TEXT NOT NULL, vector TEXT NOT NULL)")
    connection.execute("CREATE INDEX IF NOT EXISTS chunks_source ON chunks(source)")
    return connection


def ingest(source: Path, database: Path, size: int = 120, overlap: int = 25) -> tuple[int, int]:
    files = collect_files(source)
    if not files:
        raise ValueError("В указанной папке нет TXT, MD, DOCX или PDF файлов")
    prepared = []
    for path in files:
        chunks = split_text(read_document(path), size, overlap)
        if not chunks:
            continue
        source_name = str(path.resolve())
        prepared.append((source_name, chunks))
    if not prepared:
        raise ValueError("В документах не найден текст")
    with closing(connect(database)) as connection:
        with connection:
            for source_name, chunks in prepared:
                connection.execute("DELETE FROM chunks WHERE source = ?", (source_name,))
                connection.executemany(
                    "INSERT INTO chunks (source, position, text, vector) VALUES (?, ?, ?, ?)",
                    [(source_name, position, chunk, json.dumps(Counter(tokenize(chunk)), ensure_ascii=False)) for position, chunk in enumerate(chunks, 1)],
                )
    return len(prepared), sum(len(chunks) for _, chunks in prepared)


def search(question: str, database: Path, top_k: int = 3) -> list[dict]:
    if top_k < 1:
        raise ValueError("top-k должен быть положительным")
    query = Counter(token for token in tokenize(question) if token not in STOPWORDS)
    if not query or not database.exists():
        return []
    with closing(connect(database)) as connection:
        rows = connection.execute("SELECT source, position, text, vector FROM chunks").fetchall()
    if not rows:
        return []
    vectors = [json.loads(row[3]) for row in rows]
    document_frequency = Counter(token for vector in vectors for token in vector)
    count = len(rows)
    weights = {token: math.log((count + 1) / (document_frequency[token] + 1)) + 1 for token in query}
    query_norm = math.sqrt(sum((frequency * weights[token]) ** 2 for token, frequency in query.items()))
    ranked = []
    for row, vector in zip(rows, vectors):
        dot = sum(query[token] * vector.get(token, 0) * weights[token] ** 2 for token in query)
        vector_norm = math.sqrt(sum((frequency * (math.log((count + 1) / (document_frequency[token] + 1)) + 1)) ** 2 for token, frequency in vector.items()))
        score = dot / (query_norm * vector_norm) if vector_norm else 0
        score += 0.25 * sum(1 for token in query if token.isascii() and len(token) >= 4 and token in vector)
        filename_terms = set(tokenize(Path(row[0]).stem.replace("_", " ")))
        score += 0.12 * len(set(query) & filename_terms)
        phrase = " ".join(word.lower() for word in WORD.findall(question) if normalize(word) not in STOPWORDS)
        if phrase and phrase in row[2].lower():
            score += 0.25
        if score > 0:
            ranked.append({"source": row[0], "position": row[1], "text": row[2], "score": score})
    return sorted(ranked, key=lambda item: item["score"], reverse=True)[:top_k]


def relevant_matches(question: str, matches: list[dict]) -> list[dict]:
    """Оставляет только достаточно близкие к вопросу фрагменты библиотеки."""
    if not matches:
        return []

    query_terms = {
        token for token in tokenize(question)
        if token not in STOPWORDS and len(token) > 2
    }
    if not query_terms:
        return []

    best_score = float(matches[0].get("score", 0))
    selected = []
    for match in matches:
        score = float(match.get("score", 0))
        document_terms = set(tokenize(match.get("text", "")))
        overlap = query_terms & document_terms
        coverage = len(overlap) / len(query_terms)
        if score >= 0.32 or (score >= 0.14 and coverage >= 0.5 and len(overlap) >= 1):
            selected.append(match)

    if selected:
        cutoff = max(0.12, best_score * 0.45)
        selected = [match for match in selected if float(match.get("score", 0)) >= cutoff]
    return selected


def has_relevant_matches(question: str, matches: list[dict]) -> bool:
    return bool(relevant_matches(question, matches))


def short_answer(question: str, matches: list[dict]) -> str:
    if not matches:
        return "В загруженных материалах ответа нет."
    ignored = {"что", "как", "это", "такое", "где", "когда", "зачем", "какой", "какая", "какие", "работает"}
    terms = set(tokenize(question)) - ignored
    sentences = re.split(r"(?<=[.!?])\s+", matches[0]["text"].strip())
    ranked = sorted(enumerate(sentences), key=lambda pair: len(terms & set(tokenize(pair[1]))), reverse=True)
    best = ranked[0][0]
    chosen = sentences[best].strip()
    if best + 1 < len(sentences) and len(chosen) < 240:
        chosen += " " + sentences[best + 1].strip()
    return chosen[:500].strip()


def answer(
    question: str,
    database: Path,
    top_k: int = 3,
    model: str | None = None,
    url: str = "http://127.0.0.1:11434",
    history: list[dict] | None = None,
    mode: str | None = None,
    matches_override: list[dict] | None = None,
) -> tuple[str, list[dict]]:
    """Отвечает через Ollama; в режиме rag использует отобранные фрагменты библиотеки.

    В режиме ai модель отвечает самостоятельно без контекста библиотеки.
    Консольный автоматический режим выбирает между ними после оценки поиска.
    """
    if mode is None:
        mode = "ai" if model is not None else "rag"
    if mode not in {"ai", "rag"}:
        raise ValueError("Режим должен быть ai или rag")

    if mode == "rag":
        found = matches_override if matches_override is not None else search(question, database, top_k)
        matches = relevant_matches(question, found)
    else:
        matches = []
    if model is None:
        if not matches:
            return "В загруженных материалах ответа нет.", []
        return short_answer(question, matches), matches

    if mode == "rag":
        system = (
            "Ты — русскоязычный учебный помощник. В первую очередь отвечай по переданным фрагментам библиотеки проекта. "
            "Не выдумывай сведения и не приписывай их конспектам, если их там нет. "
            "Объясняй содержание своими словами, сохраняя точность. Если библиотека раскрывает только часть вопроса, "
            "чётко обозначь, какая часть подтверждается материалами. Не добавляй неподтверждённые детали."
        )
    else:
        system = (
            "Ты — полезный русскоязычный ИИ-помощник. Отвечай самостоятельно, опираясь на свои знания. "
            "Помогай с программированием, информатикой, обучением и обычными вопросами. "
            "Объясняй понятно и по делу; при необходимости давай примеры и рабочий код. "
            "Если не знаешь точного ответа, честно скажи об этом."
        )

    prompt_parts = []
    if history:
        for message in history[-12:]:
            role = "Пользователь" if message.get("role") == "user" else "Ассистент"
            content = str(message.get("content", "")).strip()
            if content:
                prompt_parts.append(f"{role}: {content}")

    if matches:
        context = "\n\n".join(
            f"[Фрагмент {index}] {item['text']}"
            for index, item in enumerate(matches, 1)
        )
        prompt_parts.append(
            "Основные материалы из библиотеки проекта. Используй их как главный источник ответа; "
            "не добавляй неподтверждённые сведения:\n" + context
        )

    prompt_parts.append(f"Пользователь: {question}\nАссистент:")
    prompt = "\n\n".join(prompt_parts)
    payload = json.dumps(
        {
            "model": model,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": 900,
                "temperature": 0.45,
                "top_p": 0.9,
                "repeat_penalty": 1.1,
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        url.rstrip("/") + "/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code == 404:
            raise RuntimeError(
                f"Модель {model} не найдена. Выполни в терминале: ollama pull {model}"
            ) from exc
        raise RuntimeError(f"Ollama вернула ошибку {exc.code}: {detail[:500]}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(
            "Не удалось подключиться к Ollama. Проверь, что Ollama запущена и модель доступна."
        ) from exc

    text = str(result.get("response", "")).strip()
    if not text:
        raise RuntimeError("Qwen вернула пустой ответ. Попробуй задать вопрос ещё раз.")
    return text, matches

