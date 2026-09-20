from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import json
import threading

STATUS_NEW = "NEW"
STATUS_CLOSED = "CLOSED"


@dataclass
class Ticket:
    """Заявка: номер, автор, текст, статус (NEW / CLOSED) и диалог сообщений."""
    id: int
    user_id: int
    user_name: str
    text: str
    status: str
    created_at: Optional[str] = field(default=None)
    # Диалог: [{"author": "user"|"mod", "name": ..., "text": ...}, ...]
    messages: list = field(default_factory=list)
    # message_id сообщения-диалога у каждого модератора: {user_id: message_id}
    dialog_ids: dict = field(default_factory=dict)


class TicketService:
    """Заявки пользователей. Хранятся в файле tickets.json."""

    def __init__(self, config: "Config") -> None:
        self._file: Path = config.data_dir / "tickets.json"
        self._lock = threading.Lock()
        self._tickets: dict[int, Ticket] = {}
        self._next_id = 1
        self._load()

    def _load(self) -> None:
        if not self._file.exists():
            return
        with self._file.open(encoding="utf-8") as f:
            raw = json.load(f)
        for item in raw:
            ticket = Ticket(
                id=item["id"],
                user_id=item["userId"],
                user_name=item["userName"],
                text=item["text"],
                status=item["status"],
                created_at=item.get("createdAt"),
                messages=item.get("messages", []),
                dialog_ids={int(k): v for k, v in item.get("dialogIds", {}).items()},
            )
            self._tickets[ticket.id] = ticket
        if self._tickets:
            self._next_id = max(self._tickets) + 1

    def create(self, user_id: int, user_name: str, text: str) -> Ticket:
        """Создаёт новую заявку и возвращает её."""
        from datetime import datetime

        with self._lock:
            ticket = Ticket(
                id=self._next_id,
                user_id=user_id,
                user_name=user_name,
                text=text,
                status=STATUS_NEW,
                created_at=datetime.now().isoformat(timespec="seconds"),
            )
            self._next_id += 1
            self._tickets[ticket.id] = ticket
            self._save()
            return ticket

    def find_last_open_by_user(self, user_id: int) -> Optional[Ticket]:
        """Последняя открытая заявка пользователя (для диалога)."""
        last = None
        for ticket in self._tickets.values():
            if ticket.user_id == user_id and ticket.status == STATUS_NEW:
                last = ticket
        return last

    def find_by_id(self, ticket_id: int) -> Optional[Ticket]:
        return self._tickets.get(ticket_id)

    def find_new(self) -> list[Ticket]:
        return sorted(
            (t for t in self._tickets.values() if t.status == STATUS_NEW),
            key=lambda t: t.id,
        )

    def get_all(self) -> list[Ticket]:
        return sorted(self._tickets.values(), key=lambda t: t.id)

    def close(self, ticket_id: int) -> None:
        with self._lock:
            ticket = self._tickets.get(ticket_id)
            if ticket is not None:
                ticket.status = STATUS_CLOSED
                self._save()

    def add_message(self, ticket_id: int, author: str, name: str, text: str,
                    sender_id: int = 0) -> None:
        """Добавляет сообщение в диалог заявки и сохраняет."""
        with self._lock:
            ticket = self._tickets.get(ticket_id)
            if ticket is not None:
                ticket.messages.append({
                    "author": author,
                    "name": name,
                    "text": text,
                    "senderId": sender_id,
                })
                self._save()

    def set_dialog_id(self, ticket_id: int, moderator_id: int, message_id: str) -> None:
        """Запоминает message_id сообщения-диалога заявки у модератора."""
        with self._lock:
            ticket = self._tickets.get(ticket_id)
            if ticket is not None:
                ticket.dialog_ids[moderator_id] = message_id
                self._save()

    def _save(self) -> None:
        data = []
        for ticket in self._tickets.values():
            d = asdict(ticket)
            d["userId"] = d.pop("user_id")
            d["userName"] = d.pop("user_name")
            d["createdAt"] = d.pop("created_at")
            data.append(d)
        with self._file.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
