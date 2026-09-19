"""Кнопки для бота техподдержки в MAX.

Типы кнопок MAX:
- callback — нажатие приходит как событие message_callback с payload;
- message  — при нажатии пользователь отправляет заданный текст
             (так делаем «меню» вместо reply-клавиатуры, которой в MAX нет).
"""

MENU_BUTTON = {"type": "message", "text": "🛠 Меню", "payload": "/mod"}

USER_BUTTONS = [
    [
        {"type": "message", "text": "📝 Заявка", "payload": "/ticket"},
        {"type": "message", "text": "📊 Статус", "payload": "/status"},
        {"type": "message", "text": "❓ FAQ", "payload": "/faq"},
    ]
]


def menu_keyboard() -> list[list[dict]]:
    """Кнопки меню модератора под сообщением."""
    return [
        [{"type": "callback", "text": "📋 Открытые заявки", "payload": "mod:list"}],
        [{"type": "callback", "text": "🛠 Модераторы", "payload": "mod:mods"}],
        [{"type": "message", "text": "🛠 Меню", "payload": "/mod"}],
    ]


def ticket_keyboard(ticket_id: int) -> list[list[dict]]:
    return [
        [
            {"type": "callback", "text": "💬 Ответить", "payload": f"mod:answer:{ticket_id}"},
            {"type": "callback", "text": "✅ Закрыть", "payload": f"mod:close:{ticket_id}"},
        ],
    ]


def close_button(ticket_id: int) -> list[list[dict]]:
    return [[
        {"type": "callback", "text": "✅ Закрыть заявку", "payload": f"mod:close:{ticket_id}"},
    ]]


def refresh_button() -> list[list[dict]]:
    return [[{"type": "callback", "text": "🔄 Обновить", "payload": "mod:list"}]]


def remove_moderator_button(user_id: int) -> list[list[dict]]:
    return [[{"type": "callback", "text": "🗑 Удалить", "payload": f"mod:remove:{user_id}"}]]


def add_moderator_button() -> list[list[dict]]:
    return [[{"type": "callback", "text": "➕ Добавить модератора", "payload": "mod:add"}]]
