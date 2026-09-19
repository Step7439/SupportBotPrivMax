"""Точка входа для запуска бота техподдержки в мессенджере MAX."""
from bot import Bot, Config, MaxApi, ModeratorService, TicketService


def main() -> None:
    try:
        config = Config()
        api = MaxApi(config)
        tickets = TicketService(config)
        moderators = ModeratorService(config)

        # При первом запуске автоматически добавляем оператора модератором,
        # чтобы не редактировать moderators.json вручную.
        if not moderators.get_all() and config.operator_id is not None:
            moderators.add(config.operator_id)
            print(f"Оператор {config.operator_id} добавлен модератором.")

        bot = Bot(config, api, tickets, moderators)

        # Меню команд бота в интерфейсе MAX
        api.set_my_commands([
            ("start", "Открыть приветствие"),
            ("myid", "Узнать свой ID"),
            ("faq", "Частые вопросы"),
            ("mod", "Панель модератора"),
        ])

        bot.run()
    except Exception as e:
        print(f"Не удалось запустить бота: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
