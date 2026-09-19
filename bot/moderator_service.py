from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot import Config


class ModeratorService:
    """Список модераторов. Хранится в файле moderators.json.

    Первый добавленный модератор считается главным оператором.
    """

    def __init__(self, config: "Config") -> None:
        self._file: Path = config.data_dir / "moderators.json"
        self._lock = threading.Lock()
        self._moderators: list[int] = []
        self._load()

    def _load(self) -> None:
        if self._file.exists():
            with self._file.open(encoding="utf-8") as f:
                self._moderators = [int(x) for x in json.load(f)]

    def is_moderator(self, user_id: int) -> bool:
        with self._lock:
            return user_id in self._moderators

    def get_all(self) -> list[int]:
        with self._lock:
            return list(self._moderators)

    def add(self, user_id: int) -> bool:
        with self._lock:
            if user_id in self._moderators:
                return False
            self._moderators.append(user_id)
            self._save()
            return True

    def remove(self, user_id: int) -> bool:
        with self._lock:
            if user_id not in self._moderators:
                return False
            self._moderators.remove(user_id)
            self._save()
            return True

    def _save(self) -> None:
        with self._file.open("w", encoding="utf-8") as f:
            json.dump(self._moderators, f, ensure_ascii=False, indent=2)
