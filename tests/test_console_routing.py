import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import console


class ConsoleRoutingTests(unittest.TestCase):
    def test_auto_mode_falls_back_to_ai_when_library_has_no_match(self):
        output = io.StringIO()
        with patch("console.search", return_value=[]), patch(
            "console.with_spinner", side_effect=lambda label, func, *args, **kwargs: func(*args, **kwargs)
        ), patch("console.answer", return_value=("Ответ от Qwen.", [])) as model_answer:
            with redirect_stdout(output):
                console.show_answer("Почему небо голубое?", [], "auto")

        self.assertEqual(model_answer.call_args.args[6], "ai")
        self.assertIn("Подходящая информация не найдена", output.getvalue())
        self.assertIn("Переключаюсь на Qwen 2.5 3B", output.getvalue())

    def test_auto_mode_uses_library_when_relevant_material_exists(self):
        match = {
            "source": str(console.SAMPLE / "python_04_коллекции.txt"),
            "position": 1,
            "text": "Метод append добавляет элемент в список.",
            "score": 0.6,
        }
        output = io.StringIO()
        with patch("console.search", return_value=[match]), patch(
            "console.with_spinner", side_effect=lambda label, func, *args, **kwargs: func(*args, **kwargs)
        ), patch("console.answer", return_value=("Ответ по библиотеке.", [match])) as model_answer:
            with redirect_stdout(output):
                console.show_answer("Что делает append в Python?", [], "auto")

        self.assertEqual(model_answer.call_args.args[6], "rag")
        self.assertEqual(model_answer.call_args.kwargs["matches_override"], [match])
        self.assertIn("Найдены подходящие материалы", output.getvalue())
        self.assertIn("Источники из библиотеки", output.getvalue())


if __name__ == "__main__":
    unittest.main()
