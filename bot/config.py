"""Настройки бота для MAX: токен из переменных окружения или файла .env."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


class Config:
    """Значения берутся из переменных окружения, а если их нет — из файла .env (KEY=VALUE)."""

    def __init__(self) -> None:
        env = self._load_env_file(Path(".env"))

        self.bot_token: str = self._required(env, "MAX_BOT_TOKEN")

        operator_value = self._value(env, "OPERATOR_ID")
        self.operator_id: Optional[int] = None
        if operator_value is not None and operator_value.strip():
            try:
                self.operator_id = int(operator_value.strip())
            except ValueError:
                print(
                    "OPERATOR_ID должен быть числом. Сейчас задан: "
                    f"\"{operator_value}\". Запускаюсь без оператора — "
                    "добавьте его позже через панель модератора."
                )

        self.data_dir: Path = Path(env.get("DATA_DIR", "data"))
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _load_env_file(file: Path) -> dict[str, str]:
        """Читает файл .env в dict. Если файла нет — возвращает пустой dict."""
        result: dict[str, str] = {}
        if not file.exists():
            return result
        try:
            for line in file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                result[key.strip()] = value.strip()
        except OSError as e:
            print(f"Не удалось прочитать .env: {e}")
        return result

    @staticmethod
    def _value(env_file: dict[str, str], key: str) -> Optional[str]:
        """Возвращает значение: сначала переменная окружения, потом файл .env."""
        from_system = os.environ.get(key, "").strip()
        if from_system:
            return from_system
        return env_file.get(key)

    @staticmethod
    def _required(env_file: dict[str, str], key: str) -> str:
        """Возвращает значение или бросает понятную ошибку, если его нет."""
        value = Config._value(env_file, key)
        if value is None or not value.strip():
            raise ValueError(
                f"Не задана настройка {key}. Укажите её в переменных окружения "
                "или в файле .env (пример — .env.example)"
            )
        return value
