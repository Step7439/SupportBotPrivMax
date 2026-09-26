"""Разовая симуляция: тестовый пользователь создаёт заявку через бота."""
from bot import Config, MaxApi, ModeratorService, TicketService
from bot.update import Update
from bot.user_handler import UserHandler


def make_update(user_id: int, user_name: str, text: str) -> Update:
    return Update(
        update_type="message_created",
        user_id=user_id,
        user_name=user_name,
        text=text,
    )


def main() -> None:
    config = Config()
    api = MaxApi(config)
    tickets = TicketService(config)
    moderators = ModeratorService(config)
    handler = UserHandler(api, tickets, moderators)

    test_user_id = 987654321
    test_user_name = "Тестовый пользователь"

    # Как будто пользователь нажал кнопку «📝 Заявка» и описал проблему
    handler.handle(make_update(test_user_id, test_user_name, "📝 Заявка"))
    handler.handle(make_update(
        test_user_id, test_user_name,
        "Не открывается раздел «Отчёты» в приложении — крутится бесконечная загрузка. "
        "Телефон Samsung, приложение версии 2.1. Это тестовая заявка от CLI.",
    ))
    print("Готово: тестовая заявка создана, модераторы уведомлены.")


if __name__ == "__main__":
    main()
