import tempfile
import unittest
import zipfile
import io
from contextlib import redirect_stdout
from unittest.mock import patch
from urllib.error import URLError
from pathlib import Path

from rag_core import answer, ingest, read_document, search, split_text


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

    def test_no_match(self):
        with tempfile.TemporaryDirectory() as directory:
            response, matches = answer("вопрос", Path(directory) / "missing.sqlite")
            self.assertEqual(matches, [])
            self.assertIn("ответа нет", response)

    def test_short_answer_and_offline_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "notes.txt"
            database = root / "index.sqlite"
            source.write_text("RAG соединяет поиск и генерацию ответа. Сначала система находит нужные фрагменты.", encoding="utf-8")
            ingest(source, database)
            response, matches = answer("Что такое RAG?", database)
            self.assertIn("RAG соединяет поиск", response)
            self.assertEqual(len(matches), 1)
            with patch("rag_core.urllib.request.urlopen", side_effect=URLError("connection refused")):
                response, _ = answer("Что такое RAG?", database, model="llama3.2:3b")
            self.assertIn("Ollama не запущена", response)
            self.assertIn("RAG соединяет поиск", response)

    def test_model_without_matching_source(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "missing.sqlite"
            with patch("rag_core.urllib.request.urlopen", return_value=io.BytesIO(b'{"response":"Use a list."}')):
                response, matches = answer("Как создать список в Python?", database, model="qwen2.5:3b")
            self.assertEqual(matches, [])
            self.assertIn("нет источника", response)
            self.assertIn("Use a list.", response)

    def test_chat_waits_for_questions(self):
        from app import main

        with patch("sys.argv", ["app.py", "chat"]), patch("builtins.input", side_effect=["Что такое RAG?", "выход"]), patch("app.show_answer") as show:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 0)
            show.assert_called_once()


if __name__ == "__main__":
    unittest.main()
