# gemini_mini.py
from __future__ import annotations
import os
import time
from pathlib import Path
from typing import List, Iterable

from google import genai


MAX_RETRIES = 5
CHUNK_SIZE = 1_200_000        # ~1.2 М символов
OVERLAP = 100_000             # ~100 к символов «перекрытие»


class Generator:
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        self.client = genai.Client(api_key=api_key)
        self.model_name = model
        self.cfg = genai.types.GenerateContentConfig(
            temperature=0.3,
            top_p=0.8,
            top_k=20,
        )

    # ---------- public ----------
    def ask(self, prompt: str) -> str:
        """Одиночный запрос, 5 попыток, иначе ''."""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=self.cfg,
                )
                return resp.text
            except Exception as exc:
                if attempt == MAX_RETRIES:
                    return ""
                time.sleep(2 ** attempt)          # эксп. бэкофф
        return ""

    def process_file(self, path: Path, task: str) -> str:
        """Обработать один файл чанками с перекрытием."""
        results = []
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            prev_tail = ""
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                # добавляем перекрытие: хвост прошлого чанка + новый
                payload = prev_tail + chunk
                results.append(self.ask(f"{task}\n\n{payload}"))
                prev_tail = chunk[-OVERLAP:]      # сохраняем хвост для след. итерации
        return "\n".join(results)

    def process_queue_file(self, queue_path: Path, task: str) -> List[str]:
        """Файл-список: построчно пути к другим файлам."""
        results = []
        with queue_path.open("r", encoding="utf-8") as q:
            for line in q:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                file_path = Path(line)
                if file_path.exists():
                    results.append(self.process_file(file_path, task))
                else:
                    results.append("")          # файл не найден
        return results
