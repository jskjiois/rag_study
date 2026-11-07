import subprocess
import sys


print("ТЕМА: Помощник по конспектам информатики", flush=True)
print("ЗАДАЧА: отвечать на вопросы по информатике 5-11 классов и Python", flush=True)
print("СХЕМА: документы -> фрагменты -> поиск SQLite -> Ollama -> ответ", flush=True)
print("РОЛИ: Воробьев - тимлид; Токачев - фронтенд; Чернявский - LLM; Полянцев - RAG", flush=True)
print("\nЗАГРУЗКА КОНСПЕКТОВ", flush=True)
subprocess.run([sys.executable, "app.py", "ingest", "sample"], check=True)
print("\nВОПРОС К МОДЕЛИ", flush=True)
subprocess.run([sys.executable, "app.py", "ask", "Что такое алгоритм?", "--model", "qwen2.5:3b"], check=True)
print("\nТЕСТЫ", flush=True)
subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], check=True)
print("\nGitHub: личные коммиты участников добавляются после их работы.", flush=True)
