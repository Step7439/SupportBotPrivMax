from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING

from bot import keyboards
from bot.update import Update

if TYPE_CHECKING:
    from bot import MaxApi, ModeratorService, TicketService

# Логотип компании для приветствия
_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "logo.png"


class UserHandler:
    """Обрабатывает сообщения обычных пользователей."""

    def __init__(
        self,
        api: "MaxApi",
        tickets: "TicketService",
        moderators: "ModeratorService",
    ) -> None:
        self._api = api
        self._tickets = tickets
        self._moderators = moderators
        # Пользователи, нажавшие «📝 Заявка» и сейчас вводящие описание
        self._pending_ticket: set[int] = set()
        self._lock = threading.Lock()

    def handle(self, update: Update) -> None:
        # Нажатие callback-кнопки от не-модератора (старое/поддельное) — игнорируем
        if update.callback_id is not None:
            return

        text = update.text.strip()

        if text in ("/start", "/help"):
            self._reset_pending(update.user_id)
            self._send_welcome(update.user_id)
            return

        if text in ("/myid", "/id"):
            self._send(update.user_id,
                       f"Ваш ID в MAX: {update.user_id}\n"
                       "Отправьте этот номер модератору, чтобы он добавил вас, "
                       "или укажите его как OPERATOR_ID в .env.")
            return

        if text in ("❓ FAQ", "/faq"):
            self._reset_pending(update.user_id)
            self._send(update.user_id, (
                "❓ Частые вопросы:\n"
                "\n"
                "1. Не запускается приложение — попробуйте очистить кэш и перезапустить.\n"
                "2. Не приходят уведомления — проверьте разрешения в настройках телефона.\n"
                "3. Ошибка входа — убедитесь, что используете актуальный логин и пароль.\n"
                "\n"
                "Не помогло? Нажмите «📝 Заявка» и опишите проблему."
            ))
            return

        if text in ("📝 Заявка", "/ticket"):
            with self._lock:
                self._pending_ticket.add(update.user_id)
            self._send(update.user_id, (
                "📝 Опишите вашу проблему одним сообщением — я создам заявку, "
                "и оператор скоро ответит вам здесь."
            ))
            return

        if text in ("📊 Статус", "/status"):
            self._reset_pending(update.user_id)
            last = self._find_last_user_ticket(update.user_id)
            if last is None:
                self._send(update.user_id, "У вас пока нет заявок. Нажмите «📝 Заявка», чтобы создать заявку.")
            else:
                status = "🟡 в работе" if last.status == "NEW" else "✅ закрыта"
                self._send(update.user_id, f"Ваша заявка #{last.id} — {status}\n\nТекст: {last.text}")
            return

        # Диалог по заявке важнее ввода новой: если модератор ждёт ответа
        # пользователя в открытой заявке, сообщение уходит в диалог,
        # а незавершённый ввод описания новой заявки сбрасываем
        ticket = self._tickets.find_last_open_by_user(update.user_id)
        if ticket is not None and any(m["author"] == "mod" for m in ticket.messages):
            self._reset_pending(update.user_id)
            last_message_author = ticket.messages[-1]["author"]
            if last_message_author == "user":
                # Пользователь уже отправил ответ — ждём реакции модератора
                self._send(update.user_id, (
                    "⏳ Ваш ответ отправлен. Ждите ответ оператора — "
                    "следующее сообщение придёт вам от поддержки."
                ))
                return
            self._send_reply(update, ticket, text)
            return

        # Описание заявки принимаем только после нажатия кнопки «📝 Заявка»
        with self._lock:
            expecting = update.user_id in self._pending_ticket
            if expecting:
                self._pending_ticket.discard(update.user_id)
        if expecting:
            self._create_ticket(update, text)
            return

        # Произвольный текст заявкой не считаем
        self._send(update.user_id, (
            "Чтобы создать заявку, нажмите кнопку «📝 Заявка» "
            "и опишите проблему одним сообщением."
        ))

    def _send_welcome(self, user_id: int) -> None:
        caption = (
            "🛠 ИТМеханизатор — Support\n\n"
            "👷 Добро пожаловать в техподдержку «ИТМеханизатор»!\n"
            "\n"
            "Как обратиться к нам:\n"
            "1. «📝 Заявка» — создать заявку\n"
            "2. «📊 Статус» — статус вашей последней заявки\n"
            "3. «❓ FAQ» — частые вопросы"
        )
        # Если последняя заявка закрыта — напоминаем об этом
        last = self._find_last_user_ticket(user_id)
        if last is not None and last.status != "NEW":
            caption += (
                f"\n\n✅ Ваша заявка #{last.id} закрыта. "
                "Если проблема осталась — создайте новую заявку кнопкой «📝 Заявка»."
            )
        if _LOGO_PATH.exists():
            try:
                self._api.send_photo(user_id, _LOGO_PATH, caption)
            except Exception as e:
                print(f"Не удалось отправить логотип: {e}")
                self._send(user_id, caption, keyboards.USER_BUTTONS)
                return
            self._send(
                user_id,
                "Выберите действие:",
                keyboards.USER_BUTTONS,
            )
        else:
            self._send(user_id, caption, keyboards.USER_BUTTONS)

    def _find_last_user_ticket(self, user_id: int):
        last = None
        for ticket in self._tickets.find_new():
            if ticket.user_id == user_id:
                last = ticket
        if last is not None:
            return last
        # Если открытых нет, ищем последнюю закрытую
        for ticket in self._tickets.get_all():
            if ticket.user_id == user_id:
                last = ticket
        return last

    def _create_ticket(self, update: Update, description: str) -> None:
        if not description.strip():
            self._send(update.user_id, (
                "📝 Опишите вашу проблему одним сообщением — я создам заявку, "
                "и оператор скоро ответит вам здесь."
            ))
            return
        ticket = self._tickets.create(update.user_id, update.user_name, description)
        self._send(update.user_id, f"✅ Заявка #{ticket.id} создана. Оператор скоро ответит вам здесь.")

        # Уведомляем всех модераторов с кнопками действий
        notice = (
            f"🔔 Новая заявка #{ticket.id} от {update.user_name}\n"
            f"\n"
            f"{description}"
        )
        self._api.send_message_to_all(
            self._moderators.get_all(),
            notice,
            keyboards.ticket_keyboard(ticket.id),
        )

    def _send_reply(self, update: Update, ticket, text: str) -> None:
        """Ответ пользователя в диалог по своей открытой заявке —
        уходит только модератору, который ведёт эту заявку."""
        self._tickets.add_message(ticket.id, "user", update.user_name, text,
                                  sender_id=update.user_id)
        notice = (
            f"💬 Ответ пользователя по заявке #{ticket.id} ({update.user_name}):\n"
            f"\n"
            f"{text}"
        )
        assignee = self._tickets.get_assignee(ticket.id)
        if assignee is not None:
            self._api.send_message(
                assignee, notice, keyboards.ticket_keyboard(ticket.id))
        else:
            # Заявка не закреплена — уведомляем всех модераторов
            self._api.send_message_to_all(
                self._moderators.get_all(),
                notice,
                keyboards.ticket_keyboard(ticket.id),
            )

    def _send(self, user_id: int, text: str, buttons=None) -> None:
        self._api.send_message(user_id, text, buttons)

    def _reset_pending(self, user_id: int) -> None:
        """Сбрасывает режим ввода описания заявки."""
        with self._lock:
            self._pending_ticket.discard(user_id)
