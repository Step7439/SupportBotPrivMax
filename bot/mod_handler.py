from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from bot import keyboards
from bot.update import Update

if TYPE_CHECKING:
    from bot import MaxApi, ModeratorService, TicketService

# Логотип компании для приветствия
_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "logo.png"


class ModHandler:
    """Обрабатывает сообщения модераторов.

    Модератор — это любой пользователь из списка ModeratorService.
    Основные действия доступны через inline-кнопки: /mod открывает меню.
    """

    def __init__(
        self,
        api: "MaxApi",
        tickets: "TicketService",
        moderators: "ModeratorService",
    ) -> None:
        self._api = api
        self._tickets = tickets
        self._moderators = moderators
        # Модератор, который сейчас вводит текст ответа: user_id -> номер заявки
        self._pending_answer: dict[int, int] = {}
        # Модератор, который сейчас вводит ID нового модератора
        self._pending_add: set[int] = set()
        self._lock = threading.Lock()

    def handle(self, update: Update) -> None:
        if update.callback_id is not None:
            self._handle_button(update)
            return

        text = update.text.strip()

        if text in ("/mod", "🛠 Меню", "/help"):
            # Открытие меню сбрасывает незавершённые режимы (ожидание ответа/ID)
            self._reset_pending(update.user_id)
            self._send_menu(update.user_id)
            return

        if text == "/start":
            self._send_welcome(update.user_id)
            return

        if text in ("/myid", "/id"):
            self._send(update.user_id, f"Ваш ID в MAX: {update.user_id}")
            return

        if text in ("/cancel", "отмена", "Отмена", "❌ Отмена"):
            self._reset_pending(update.user_id)
            self._send_menu(update.user_id)
            return

        with self._lock:
            ticket_id = self._pending_answer.pop(update.user_id, None)
            is_adding = update.user_id in self._pending_add
            if is_adding:
                self._pending_add.discard(update.user_id)
        if ticket_id is not None:
            self._send_answer(update, ticket_id, text)
            return
        if is_adding:
            self._add_moderator(update, text)
            return

        # Неизвестное сообщение — подсказываем и сразу даём кнопку меню
        self._send(update.user_id, "Не понял сообщение. Вот меню модератора:", keyboards.menu_keyboard())

    # --- Приветствие ---

    def _send_welcome(self, user_id: int) -> None:
        caption = (
            "🛠 ИТМеханизатор — Support\n\n"
            "Панель модератора техподдержки.\n"
            "Используйте кнопки под сообщениями или команду /mod."
        )
        if _LOGO_PATH.exists():
            try:
                self._api.send_photo(user_id, _LOGO_PATH, caption)
            except Exception as e:
                print(f"Не удалось отправить логотип: {e}")
                self._send(user_id, caption, keyboards.menu_keyboard())
                return
            self._send(user_id, "Выберите действие:", keyboards.menu_keyboard())
        else:
            self._send(user_id, caption, keyboards.menu_keyboard())

    def _send_menu(self, user_id: int) -> None:
        self._send(user_id, "🛠 Меню модератора:", keyboards.menu_keyboard())

    # --- Кнопки ---

    def _handle_button(self, update: Update) -> None:
        """Обрабатывает нажатия inline-кнопок."""
        # Подтверждаем нажатие сразу: callback_id живёт недолго,
        # а отправка сообщений с троттлингом может занять секунды
        self._api.answer_callback(update.callback_id)

        data = update.callback_data

        if data == "mod:list":
            self._cmd_list(update.user_id)
        elif data == "mod:mods":
            self._cmd_mods(update.user_id)
        elif data == "mod:add":
            self._start_add(update)
        elif data.startswith("mod:answer:"):
            ticket_id = self._parse_callback_id(update, data)
            if ticket_id is not None:
                self._start_answer(update, ticket_id)
        elif data.startswith("mod:close:"):
            ticket_id = self._parse_callback_id(update, data)
            if ticket_id is not None:
                self._close_ticket(update.user_id, ticket_id)
        elif data.startswith("mod:remove:"):
            user_id = self._parse_callback_id(update, data)
            if user_id is not None:
                self._remove_moderator(update, user_id)
        elif data.startswith("mod:cancel:"):
            self._reset_pending(update.user_id)
            self._send(update.user_id, "❌ Режим ввода отменён. Вот меню:", keyboards.menu_keyboard())
        else:
            self._send(update.user_id, "Неизвестная кнопка. Откройте меню: /mod")

    def _parse_callback_id(self, update: Update, data: str) -> Optional[int]:
        """Достаёт число из payload вида 'mod:answer:5'. Некорректные — игнорируем."""
        raw = data.rsplit(":", 1)[1]
        try:
            return int(raw)
        except ValueError:
            self._send(update.user_id, "Некорректная кнопка. Откройте меню: /mod")
            return None

    def _cmd_list(self, user_id: int) -> None:
        """Кнопка «Открытые заявки» — показать каждую с кнопками действий."""
        open_tickets = self._tickets.find_new()
        if not open_tickets:
            self._send(user_id, "Открытых заявок нет 🎉", keyboards.refresh_button())
            return
        self._send(user_id, f"📋 Открытые заявки: {len(open_tickets)}")
        for ticket in open_tickets:
            self._send(
                user_id,
                f"#{ticket.id} — {ticket.user_name}\n\n{ticket.text}",
                keyboards.ticket_keyboard(ticket.id),
            )

    def _start_answer(self, update: Update, ticket_id: int) -> None:
        """Кнопка «Ответить» — запоминаем заявку и ждём текст ответа."""
        ticket = self._tickets.find_by_id(ticket_id)
        if ticket is None or ticket.status != "NEW":
            self._send(update.user_id, f"Заявка #{ticket_id} не найдена или уже закрыта.")
            return
        with self._lock:
            self._pending_answer[update.user_id] = ticket_id
        self._send(
            update.user_id,
            f"💬 Напишите ответ по заявке #{ticket_id} — я отправлю его {ticket.user_name}.",
            keyboards.cancel_button(ticket_id),
        )

    def _send_answer(self, update: Update, ticket_id: int, text: str) -> None:
        ticket = self._tickets.find_by_id(ticket_id)
        if ticket is None:
            self._send(update.user_id, f"Заявка #{ticket_id} не найдена.")
            return
        if ticket.status != "NEW":
            self._send(update.user_id, f"Заявка #{ticket_id} уже закрыта — ответ не отправлен.")
            return
        self._api.send_message(
            ticket.user_id,
            f"💬 Ответ поддержки по заявке #{ticket_id}:\n\n{text}",
        )
        self._send(
            update.user_id,
            f"Ответ отправлен автору заявки #{ticket_id}.",
            keyboards.close_button(ticket_id),
        )

    def _close_ticket(self, user_id: int, ticket_id: int) -> None:
        """Кнопка «Закрыть» — закрывает заявку #<id>."""
        ticket = self._tickets.find_by_id(ticket_id)
        if ticket is None:
            self._send(user_id, f"Заявка #{ticket_id} не найдена.")
            return
        if ticket.status != "NEW":
            # Уже закрыта — не дублируем уведомление автору
            self._send(user_id, f"Заявка #{ticket_id} уже закрыта.")
            return
        self._tickets.close(ticket_id)
        self._api.send_message(
            ticket.user_id,
            f"✅ Ваша заявка #{ticket_id} закрыта. Если проблема осталась — напишите нам снова.",
        )
        self._send(user_id, f"Заявка #{ticket_id} закрыта.")

    def _cmd_mods(self, user_id: int) -> None:
        """Кнопка «Модераторы» — список модераторов с кнопками."""
        all_mods = self._moderators.get_all()
        if not all_mods:
            self._send(user_id, "Модераторов нет. Добавьте первого кнопкой ниже.")
        else:
            self._send(user_id, "🛠 Модераторы — нажмите, чтобы удалить:")
            for user_id in all_mods:
                self._send(
                    user_id,
                    f"• {user_id}",
                    keyboards.remove_moderator_button(user_id),
                )
        self._send(user_id, "Добавить модератора:", keyboards.add_moderator_button())

    def _start_add(self, update: Update) -> None:
        with self._lock:
            self._pending_add.add(update.user_id)
        self._send(
            update.user_id,
            "Отправьте ID пользователя MAX нового модератора одним сообщением.",
            keyboards.cancel_button(0),
        )

    def _add_moderator(self, update: Update, text: str) -> None:
        try:
            user_id = int(text)
        except ValueError:
            with self._lock:
                self._pending_add.add(update.user_id)
            self._send(
                update.user_id,
                "ID должен быть числом. Попробуйте ещё раз или напишите /mod для меню.",
            )
            return
        if user_id <= 0:
            with self._lock:
                self._pending_add.add(update.user_id)
            self._send(update.user_id, "ID должен быть положительным числом. Попробуйте ещё раз.")
            return
        if self._moderators.add(user_id):
            self._send(update.user_id, f"Модератор {user_id} добавлен. Он увидит команды /mod.")
            self._api.send_message(
                user_id,
                "Вас добавили в модераторы техподдержки «ИТМеханизатор». Напишите /mod, чтобы начать.",
            )
        else:
            self._send(update.user_id, f"{user_id} уже модератор.")

    def _remove_moderator(self, update: Update, user_id: int) -> None:
        all_mods = self._moderators.get_all()
        if len(all_mods) <= 1:
            self._send(update.user_id, "Нельзя удалить последнего модератора — бот останется без поддержки.")
            return
        if self._moderators.remove(user_id):
            self._send(update.user_id, f"Модератор {user_id} удалён.")
        else:
            self._send(update.user_id, f"{user_id} не является модератором.")

    def _send(self, user_id: int, text: str, buttons=None) -> None:
        self._api.send_message(user_id, text, buttons)

    def _reset_pending(self, user_id: int) -> None:
        """Сбрасывает незавершённые режимы (ожидание ответа / ID модератора)."""
        with self._lock:
            self._pending_answer.pop(user_id, None)
            self._pending_add.discard(user_id)
