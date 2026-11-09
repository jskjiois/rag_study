import tempfile
import json
import unittest
import zipfile
import io
from contextlib import redirect_stdout
from unittest.mock import patch
from urllib.error import URLError
from pathlib import Path

from rag_core import answer, exact_string_concat_code, has_relevant_matches, ingest, read_document, search, split_text


class RagCoreTests(unittest.TestCase):
    def test_chunk_overlap(self):
        self.assertEqual(split_text("один два три четыре пять", 3, 1), ["один два три", "три четыре пять"])

    def test_docx_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.docx"
            xml = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Первый абзац</w:t></w:r></w:p><w:p><w:r><w:t>Второй абзац</w:t></w:r></w:p></w:body></w:document>'
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", xml)
            self.assertEqual(read_document(path), "Первый абзац\nВторой абзац")

    def test_ingest_search_and_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "notes.txt"
            database = root / "index.sqlite"
            source.write_text("Векторный поиск находит близкие документы.\n\nСолнце освещает Землю.", encoding="utf-8")
            self.assertEqual(ingest(source, database, 5, 1)[0], 1)
            self.assertIn("Векторный поиск", search("векторный поиск", database, 1)[0]["text"])
            source.write_text("Луна вращается вокруг Земли.", encoding="utf-8")
            ingest(source, database, 5, 1)
            self.assertEqual(search("векторный поиск", database), [])
            self.assertTrue(search("Луна", database))

    def test_library_relevance_and_fallback_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "notes.txt"
            database = root / "index.sqlite"
            source.write_text(
                "Алгоритм - это последовательность шагов. Машинное обучение находит закономерности по примерам. "
                "В Python метод append добавляет элемент в список. Для перевода числа в двоичную систему делят его на два.",
                encoding="utf-8",
            )
            ingest(source, database)
            self.assertTrue(has_relevant_matches("Что такое алгоритм?", search("Что такое алгоритм?", database)))
            self.assertTrue(has_relevant_matches("Объясни машинное обучение", search("Объясни машинное обучение", database)))
            self.assertTrue(has_relevant_matches("Что делает append в Python?", search("Что делает append в Python?", database)))
            self.assertFalse(has_relevant_matches("Почему небо голубое?", search("Почему небо голубое?", database)))

    def test_exact_string_concat_preserves_quoted_phrases(self):
        code = exact_string_concat_code('Напиши код, который соединяет строки "hello there" и "good bye"')
        self.assertEqual(
            code,
            "first = 'hello there'\nsecond = 'good bye'\nresult = first + second\nprint(result)",
        )

    def test_exact_string_concat_does_not_trigger_for_general_question(self):
        self.assertIsNone(exact_string_concat_code("Что значит соединить пись и сись?"))


    def test_no_match(self):
        with tempfile.TemporaryDirectory() as directory:
            response, matches = answer("вопрос", Path(directory) / "missing.sqlite")
            self.assertEqual(matches, [])
            self.assertIn("ответа нет", response)

    def test_rag_without_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "notes.txt"
            database = root / "index.sqlite"
            source.write_text("RAG соединяет поиск и генерацию ответа. Сначала система находит нужные фрагменты.", encoding="utf-8")
            ingest(source, database)
            response, matches = answer("Что такое RAG?", database)
            self.assertIn("RAG соединяет поиск", response)
            self.assertEqual(len(matches), 1)

    def test_ai_mode_uses_model_without_searching_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "notes.txt"
            database = root / "index.sqlite"
            source.write_text("Уникальное слово конспекта: квазарныймяч.", encoding="utf-8")
            ingest(source, database)
            captured = {}
            def fake_urlopen(request, timeout=0):
                captured["payload"] = json.loads(request.data.decode("utf-8"))
                return io.BytesIO(json.dumps({"response": "Я отвечаю как обычный ИИ."}, ensure_ascii=False).encode("utf-8"))
            with patch("rag_core.urllib.request.urlopen", side_effect=fake_urlopen):
                response, matches = answer(
                    "Объясни, что такое рекурсия.", database, model="qwen2.5:3b",
                    history=[{"role": "user", "content": "Привет"}, {"role": "assistant", "content": "Здравствуйте!"}],
                )
            self.assertEqual(matches, [])
            self.assertIn("обычный ИИ", response)
            self.assertIn("Объясни, что такое рекурсия", captured["payload"]["prompt"])
            self.assertIn("Здравствуйте!", captured["payload"]["prompt"])
            self.assertIn("Не заменяй", captured["payload"]["system"])
            self.assertEqual(captured["payload"]["options"]["temperature"], 0.1)
            self.assertEqual(captured["payload"]["options"]["seed"], 42)

    def test_rag_mode_adds_notes_as_optional_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "notes.txt"
            database = root / "index.sqlite"
            source.write_text("Рекурсия — это вызов функцией самой себя.", encoding="utf-8")
            ingest(source, database)
            captured = {}
            def fake_urlopen(request, timeout=0):
                captured["payload"] = json.loads(request.data.decode("utf-8"))
                return io.BytesIO(json.dumps({"response": "Рекурсия — это вызов функции самой себя."}, ensure_ascii=False).encode("utf-8"))
            with patch("rag_core.urllib.request.urlopen", side_effect=fake_urlopen):
                response, matches = answer("Что такое рекурсия?", database, model="qwen2.5:3b", mode="rag")
            self.assertTrue(matches)
            self.assertIn("Основные материалы из библиотеки", captured["payload"]["prompt"])
            self.assertIn("главный источник ответа", captured["payload"]["prompt"])

    def test_ollama_offline_reports_error_in_ai_mode(self):
        with patch("rag_core.urllib.request.urlopen", side_effect=URLError("connection refused")):
            with self.assertRaisesRegex(RuntimeError, "Не удалось подключиться к Ollama"):
                answer("Что такое RAG?", Path("missing.sqlite"), model="qwen2.5:3b")

    def test_chat_waits_for_questions(self):
        from app import main

        with patch("sys.argv", ["app.py", "chat"]), patch("builtins.input", side_effect=["Что такое RAG?", "выход"]), patch("app.show_answer") as show:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 0)
            show.assert_called_once()


if __name__ == "__main__":
    unittest.main()
