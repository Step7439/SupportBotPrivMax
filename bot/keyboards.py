"""Кнопки для бота техподдержки в мессенджере MAX.

Типы кнопок MAX:
- callback — нажатие приходит как событие message_callback с payload;
- message  — при нажатии пользователь отправляет заданный текст
             (так делаем «меню» вместо reply-клавиатуры, которой в MAX нет).
"""

USER_BUTTONS = [
    [
        {"type": "message", "text": "📝 Заявка", "payload": "/ticket"},
        {"type": "message", "text": "📊 Статус", "payload": "/status"},
        {"type": "message", "text": "❓ FAQ", "payload": "/faq"},
    ]
]


def menu_row() -> list[dict]:
    """Ряд главных кнопок — добавляется внизу клавиатур модератора,
    чтобы «Открытые заявки» и «Модераторы» всегда были под рукой."""
    return [
        {"type": "callback", "text": "📋 Открытые заявки", "payload": "mod:list"},
        {"type": "callback", "text": "🛠 Модераторы", "payload": "mod:mods"},
    ]


def with_menu(buttons: list[list[dict]]) -> list[list[dict]]:
    """Добавляет ряд главных кнопок внизу клавиатуры (если его там ещё нет)."""
    if buttons and buttons[-1] == menu_row():
        return buttons
    return buttons + [menu_row()]


def menu_keyboard() -> list[list[dict]]:
    """Кнопки меню модератора под сообщением."""
    return [menu_row()]


def status_button() -> list[list[dict]]:
    """Кнопка «Статус» — прикрепляется к сообщениям модератора пользователю."""
    return [
        [{"type": "message", "text": "📊 Статус", "payload": "/status"}],
    ]


def ticket_keyboard(ticket_id: int) -> list[list[dict]]:
    return with_menu([
        [
            {"type": "callback", "text": "💬 Ответить", "payload": f"mod:answer:{ticket_id}"},
            {"type": "callback", "text": "✅ Закрыть", "payload": f"mod:close:{ticket_id}"},
        ],
    ])


def close_button(ticket_id: int) -> list[list[dict]]:
    return with_menu([[
        {"type": "callback", "text": "✅ Закрыть заявку", "payload": f"mod:close:{ticket_id}"},
    ]])


def cancel_button(ticket_id: int) -> list[list[dict]]:
    """Промпт «Напишите ответ» — только надпись, без кнопок.

    Отменить ввод можно командой /mod или /cancel.
    """
    return []


def refresh_button() -> list[list[dict]]:
    return with_menu([[{"type": "callback", "text": "🔄 Обновить", "payload": "mod:list"}]])


def remove_moderator_button(user_id: int) -> list[list[dict]]:
    return with_menu([[
        {"type": "callback", "text": "🗑 Удалить", "payload": f"mod:remove:{user_id}"},
    ]])


def add_moderator_button() -> list[list[dict]]:
    return with_menu([[{"type": "callback", "text": "➕ Добавить модератора", "payload": "mod:add"}]])