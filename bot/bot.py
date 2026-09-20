from __future__ import annotations

import time
from typing import TYPE_CHECKING

from bot.max_api import AuthError
from bot.mod_handler import ModHandler
from bot.update import Update
from bot.user_handler import UserHandler

if TYPE_CHECKING:
    from bot import Config, MaxApi, ModeratorService, TicketService


class Bot:
    """Роутер: получает события от MAX и раздаёт их обработчикам."""

    def __init__(
        self,
        config: "Config",
        api: "MaxApi",
        tickets: "TicketService",
        moderators: "ModeratorService",
    ) -> None:
        self._api = api
        self._moderators = moderators
        self.user_handler = UserHandler(api, tickets, moderators)
        self.mod_handler = ModHandler(api, tickets, moderators)

    def run(self) -> None:
        print("Бот техподдержки (MAX) запущен.")
        marker = None
        while True:
            try:
                updates, marker = self._get_updates(marker)
                for update in updates:
                    self._handle(update)
            except KeyboardInterrupt:
                raise
            except AuthError as e:
                print(f"Остановка: {e}")
                raise SystemExit(1)
            except Exception as e:
                print(f"Сбой связи с MAX, повтор через 5 секунд: {e}")
                time.sleep(5)

    def _get_updates(self, marker):
        return self._api.get_updates(marker)

    def _handle(self, update: Update) -> None:
        if not update.text.strip() and update.callback_id is None:
            return
        try:
            if self._moderators.is_moderator(update.user_id):
                self.mod_handler.handle(update)
            else:
                self.user_handler.handle(update)
        except Exception as e:
            print(f"Ошибка при обработке события от {update.user_id}: {e}")
