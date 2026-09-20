from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

from bot.update import Update

if TYPE_CHECKING:
    from bot import Config

# Лимит MAX: не более 2 сообщений в секунду в один диалог
_SEND_INTERVAL = 0.55

# Корневые сертификаты Минцифры (Russian Trusted CA) — их нет в стандартных хранилищах
_CERTS_DIR = Path(__file__).resolve().parent.parent / "certs"


class AuthError(RuntimeError):
    """Токен бота отклонён MAX (401) — продолжать работу бессмысленно."""


def _make_ssl_context() -> ssl.SSLContext:
    """SSL-контекст с системными CA + сертификатами Минцифры."""
    context = ssl.create_default_context()
    for cert_file in sorted(_CERTS_DIR.glob("*.crt")):
        try:
            context.load_verify_locations(cafile=str(cert_file))
        except (ssl.SSLError, OSError) as e:
            print(f"Не удалось добавить сертификат {cert_file.name}: {e}")
    return context


class MaxApi:
    """Обёртка над MAX Bot API (platform-api2.max.ru).

    Токен передаётся в заголовке Authorization (query-параметры больше не поддерживаются).
    """

    def __init__(self, config: "Config") -> None:
        self._base_url = "https://platform-api2.max.ru"
        self._token = config.bot_token
        self._last_send: dict[int, float] = {}
        self._ssl_context = _make_ssl_context()

    # --- Обновления (long polling) ---

    def get_updates(self, marker: Optional[int]) -> tuple[list[Update], Optional[int]]:
        """Возвращает (обновления, следующий marker)."""
        params = ["timeout=30"]
        if marker is not None:
            params.append(f"marker={marker}")
        root = self._send_get("/updates?" + "&".join(params))

        updates: list[Update] = []
        for node in root.get("updates", []):
            update = self._parse_update(node)
            if update is not None:
                # user_id = 0 значит, структура события отличается от ожидаемой —
                # логируем сырой JSON, чтобы быстро найти расхождение с докой
                if update.user_id == 0:
                    print(f"Не удалось распознать user_id в событии: {node}")
                updates.append(update)
        return updates, root.get("marker")

    def _parse_update(self, node: dict) -> Optional[Update]:
        update_type = node.get("update_type")

        if update_type == "message_created":
            message = node.get("message", {})
            sender = message.get("sender", {})
            body = message.get("body", {})
            return Update(
                update_type=update_type,
                user_id=sender.get("user_id", 0),
                user_name=sender.get("name", "Пользователь"),
                text=body.get("text", "") or "",
            )

        if update_type == "message_callback":
            callback = node.get("callback", {})
            # Нажавший кнопку лежит в callback.user (по факту из логов MAX);
            # message.sender — это сам бот, его брать нельзя
            sender = callback.get("user") or callback.get("sender") or {}
            payload = callback.get("payload")
            if isinstance(payload, str):
                data = payload
            else:
                data = json.dumps(payload, ensure_ascii=False) if payload else ""
            return Update(
                update_type=update_type,
                user_id=sender.get("user_id", 0),
                user_name=sender.get("name", "Пользователь"),
                text="",
                callback_id=callback.get("callback_id"),
                callback_data=data,
            )

        if update_type == "bot_started":
            user = node.get("user", {})
            return Update(
                update_type=update_type,
                user_id=user.get("user_id", 0),
                user_name=user.get("name", "Пользователь"),
                text="/start",
            )

        # Остальные события боту техподдержки не нужны
        return None

    # --- Отправка сообщений ---

    def send_message(
        self,
        user_id: int,
        text: str,
        buttons: Optional[list[list[dict]]] = None,
    ) -> Optional[str]:
        """Отправляет текстовое сообщение, опционально с inline-клавиатурой.

        Личные диалоги в MAX адресуются по user_id получателя, а не по chat_id
        (chat_id из события может не существовать для /messages → 404).

        buttons — ряды кнопок: {"type": "callback", "text": "...", "payload": "..."}
        Возвращает message_id отправленного сообщения (для последующего
        редактирования) или None, если MAX не вернул идентификатор.
        """
        if len(text) > 4000:
            text = text[:4000] + "\n…(сообщение обрезано)"
        body: dict = {"text": text}
        if buttons:
            body["attachments"] = [{
                "type": "inline_keyboard",
                "payload": {"buttons": buttons},
            }]
        self._throttle(user_id)
        root = self._send_post(f"/messages?user_id={user_id}", body)
        if not root.get("success", True):
            print(f"MAX не принял сообщение: {root}")
            return None
        message = root.get("message") or root
        return (message.get("body") or {}).get("mid")

    def edit_message(
        self,
        user_id: int,
        message_id: str,
        text: str,
        buttons: Optional[list[list[dict]]] = None,
    ) -> bool:
        """Редактирует отправленное ботом сообщение (PUT /messages).

        Сообщения с inline_keyboard редактируются без ограничения по сроку.
        Возвращает True при успехе — иначе можно отправить сообщение заново.
        """
        if len(text) > 4000:
            text = text[:4000] + "\n…(сообщение обрезано)"
        body: dict = {"text": text}
        if buttons:
            body["attachments"] = [{
                "type": "inline_keyboard",
                "payload": {"buttons": buttons},
            }]
        self._throttle(user_id)
        root = self._send_put(f"/messages?message_id={message_id}", body)
        if not root:
            return False
        if not root.get("success", True):
            print(f"MAX не отредактировал сообщение: {root}")
            return False
        return True

    def answer_callback(self, callback_id: Optional[str], message: Optional[dict] = None) -> None:
        """Отвечает на нажатие кнопки (POST /answers).

        message — новое тело сообщения, которым заменяется сообщение с кнопкой.
        Без message отправляем одноразовое notification — MAX требует
        хотя бы одно из двух (`message` or `notification` required).
        """
        if not callback_id:
            return
        body: dict = {"notification": "Ок"}
        if message is not None:
            body["message"] = message
        root = self._send_post(f"/answers?callback_id={callback_id}", body)
        if not root.get("success", True):
            print(f"MAX не принял ответ на callback: {root}")

    def send_message_to_all(self, user_ids: list[int], text: str,
                            buttons: Optional[list[list[dict]]] = None) -> None:
        for user_id in user_ids:
            self.send_message(user_id, text, buttons)

    def _throttle(self, user_id: int) -> None:
        """Держит паузу между сообщениями в один диалог (лимит MAX: 2/сек)."""
        now = time.monotonic()
        last = self._last_send.get(user_id, 0.0)
        wait = _SEND_INTERVAL - (now - last)
        if wait > 0:
            time.sleep(wait)
        self._last_send[user_id] = time.monotonic()

    # --- Медиафайлы: логотип ---

    def send_photo(self, user_id: int, photo_path: Path, caption: str = "") -> None:
        """Отправляет картинку с подписью: POST /uploads → token → POST /messages."""
        token = self._upload_image(photo_path)
        attachments: list[dict] = [{"type": "image", "payload": {"token": token}}]
        if buttons := self._logo_buttons():
            attachments.append({
                "type": "inline_keyboard",
                "payload": {"buttons": buttons},
            })
        self._throttle(user_id)
        root = self._send_post(f"/messages?user_id={user_id}", {
            "text": caption[:4000],
            "attachments": attachments,
        })
        if not root.get("success", True):
            print(f"MAX не принял фото: {root}")

    @staticmethod
    def _logo_buttons() -> Optional[list[list[dict]]]:
        return None

    def _upload_image(self, photo_path: Path) -> str:
        """Загружает изображение и возвращает token для вложения."""
        root = self._send_post("/uploads?type=image", {})
        upload_url = root.get("url")
        if not upload_url:
            raise RuntimeError(f"MAX не вернул URL для загрузки: {root}")

        data = Path(photo_path).read_bytes()
        request = urllib.request.Request(
            upload_url,
            data=data,
            headers={"Content-Type": "image/png"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60, context=self._ssl_context) as response:
            body = json.loads(response.read().decode("utf-8"))
        token = body.get("token")
        if not token:
            raise RuntimeError(f"MAX не вернул token после загрузки: {body}")
        return token

    # --- Команды бота ---

    def set_my_commands(self, commands: list[tuple[str, str]]) -> None:
        """Регистрирует меню команд (PATCH /me/commands)."""
        body = {"commands": [
            {"name": name, "description": description}
            for name, description in commands
        ]}
        self._send_patch("/me/commands", body)

    # --- Низкоуровневые запросы ---

    def _send_get(self, path: str) -> dict:
        request = urllib.request.Request(
            self._base_url + path,
            headers={"Authorization": self._token},
            method="GET",
        )
        return self._read_response(request, self._ssl_context)

    def _send_post(self, path: str, body: dict) -> dict:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self._base_url + path,
            data=data,
            headers={
                "Authorization": self._token,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        return self._read_response(request, self._ssl_context)

    def _send_put(self, path: str, body: dict) -> dict:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self._base_url + path,
            data=data,
            headers={
                "Authorization": self._token,
                "Content-Type": "application/json",
            },
            method="PUT",
        )
        return self._read_response(request, self._ssl_context)

    def delete_message(self, user_id: int, message_id: str) -> bool:
        """Удаляет сообщение, отправленное ботом (DELETE /messages)."""
        if not message_id:
            return False
        self._throttle(user_id)
        root = self._send_delete(f"/messages?message_id={message_id}")
        if not root:
            return False
        if not root.get("success", True):
            print(f"MAX не удалил сообщение: {root}")
            return False
        return True

    def _send_delete(self, path: str) -> dict:
        request = urllib.request.Request(
            self._base_url + path,
            headers={"Authorization": self._token},
            method="DELETE",
        )
        return self._read_response(request, self._ssl_context)

    def _send_patch(self, path: str, body: dict) -> dict:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self._base_url + path,
            data=data,
            headers={
                "Authorization": self._token,
                "Content-Type": "application/json",
            },
            method="PATCH",
        )
        return self._read_response(request, self._ssl_context)

    @staticmethod
    def _read_response(request: urllib.request.Request, context: ssl.SSLContext) -> dict:
        try:
            with urllib.request.urlopen(request, timeout=60, context=context) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code == 401:
                # Токен недействителен — ретраи не помогут, останавливаемся
                raise AuthError(
                    f"MAX отклонил токен бота (HTTP 401). "
                    "Проверьте MAX_BOT_TOKEN в .env (dev.max.ru → Чат-боты → Настройки)."
                )
            # 403 и прочее — точечный отказ (устаревший callback, запрет действия),
            # бот продолжает работу; печатаем адрес и ответ MAX для диагностики
            print(f"Ошибка MAX API ({e.code}) на {request.full_url}: {detail}")
            return {}
