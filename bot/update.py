from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Update:
    """Упрощённое представление события от MAX Bot API.

    MaxApi сам распарсивает JSON и складывает сюда только то, что нужно боту.
    Для нажатия inline-кнопки заполняются callback_id и callback_data.
    """

    update_type: str          # message_created | message_callback | bot_started | ...
    chat_id: int              # куда отвечать
    user_id: int              # кто написал (важно для проверки прав)
    user_name: str
    text: str
    callback_id: Optional[str] = None  # если это нажатие кнопки
    callback_data: str = ""            # payload нажатой кнопки
