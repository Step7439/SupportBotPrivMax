"""Тесты MAX-бота: пользователи, модераторы, кнопки, заявки, парсинг API."""
from __future__ import annotations

import io
import json
import ssl
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from bot.max_api import MaxApi
from bot.mod_handler import ModHandler
from bot.moderator_service import ModeratorService
from bot.ticket_service import TicketService
from bot.update import Update
from bot.user_handler import UserHandler


# --- Фейки ---

@dataclass
class Sent:
    chat_id: int
    text: str
    buttons: object


class FakeApi:
    """Запоминает все отправленные сообщения вместо реального MAX."""

    def __init__(self) -> None:
        self.sent: list[Sent] = []
        self.callback_answers: list = []
        self.photos: list[tuple] = []

    def send_message(self, user_id, text, buttons=None):
        self.sent.append(Sent(user_id, text, buttons))

    def send_message_to_all(self, user_ids, text, buttons=None):
        for user_id in user_ids:
            self.send_message(user_id, text, buttons)

    def answer_callback(self, callback_id, message=None):
        self.callback_answers.append(callback_id)

    def send_photo(self, user_id, photo_path, caption=""):
        self.photos.append((user_id, str(photo_path), caption))

    def to(self, user_id: int) -> list[Sent]:
        return [s for s in self.sent if s.chat_id == user_id]

    def texts(self, user_id: int) -> list[str]:
        return [s.text for s in self.to(user_id)]


class FakeConfig:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.bot_token = "TEST"
        self.operator_id = None


def make_update(update_type, user_id, text, callback_id=None, callback_data=""):
    return Update(
        update_type=update_type,
        user_id=user_id,
        user_name="Тест",
        text=text,
        callback_id=callback_id,
        callback_data=callback_data,
    )


class BaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        self.api = FakeApi()
        self.config = FakeConfig(self.data_dir)
        self.tickets = TicketService(self.config)
        self.moderators = ModeratorService(self.config)
        self.moderators.add(100)
        self.users = UserHandler(self.api, self.tickets, self.moderators)
        self.mods = ModHandler(self.api, self.tickets, self.moderators)

    def tearDown(self):
        self.tmp.cleanup()

    def press(self, payload: str, user_id: int = 100, cid: str = "cb1"):
        """Нажатие inline-кнопки."""
        self.mods.handle(make_update(
            "message_callback", user_id, "", callback_id=cid, callback_data=payload))

    def say(self, text: str, user_id: int = 100):
        """Текстовое сообщение."""
        if self.moderators.is_moderator(user_id):
            self.mods.handle(make_update("message_created", user_id, text))
        else:
            self.users.handle(make_update("message_created", user_id, text))


# --- Тесты пользователя ---

class TestUserHandler(BaseTest):
    def test_start_shows_logo_and_buttons(self):
        self.say("/start", user_id=200)
        # Приветствие с логотипом и подписью Support
        self.assertIn("ИТМеханизатор — Support", self.api.photos[0][2])
        buttons_msg = [s for s in self.api.sent if s.buttons]
        self.assertEqual(len(buttons_msg), 1)
        self.assertEqual(buttons_msg[0].buttons[0][0]["payload"], "/ticket")

    def test_start_without_logo_falls_back_to_text(self):
        from bot import user_handler
        with patch.object(user_handler, "_LOGO_PATH", Path("нет_такого.png")):
            self.say("/start", user_id=200)
        msg = self.api.to(200)[0]
        self.assertIn("ИТМеханизатор — Support", msg.text)
        self.assertEqual(msg.buttons[0][1]["payload"], "/status")

    def test_faq_button(self):
        self.say("❓ FAQ", user_id=200)
        self.assertIn("Частые вопросы", self.api.texts(200)[0])

    def test_ticket_button_asks_description(self):
        self.say("📝 Заявка", user_id=200)
        self.assertIn("Опишите", self.api.texts(200)[0])

    def test_status_no_tickets(self):
        self.say("📊 Статус", user_id=200)
        self.assertIn("нет заявок", self.api.texts(200)[0])

    def test_plain_text_creates_ticket(self):
        self.say("не работает вход", user_id=200)
        self.assertIn("Заявка #1 создана", self.api.texts(200)[0])
        # Модератор получил уведомление с кнопками
        mod_msg = self.api.to(100)[0]
        self.assertIn("Новая заявка #1", mod_msg.text)
        self.assertEqual(mod_msg.buttons[0][0]["payload"], "mod:answer:1")
        self.assertEqual(mod_msg.buttons[0][1]["payload"], "mod:close:1")

    def test_empty_text_does_not_create_ticket(self):
        # Пустой текст отфильтровывается в Bot._handle, а обработчик
        # на всякий случай просит описание, но заявку не создаёт
        self.say("", user_id=200)
        self.assertEqual(self.tickets.get_all(), [])

    def test_status_after_ticket(self):
        self.say("не работает вход", user_id=200)
        self.say("📊 Статус", user_id=200)
        self.assertIn("в работе", self.api.texts(200)[-1])

    def test_status_closed_ticket(self):
        self.say("не работает вход", user_id=200)
        self.tickets.close(1)
        self.say("📊 Статус", user_id=200)
        self.assertIn("закрыта", self.api.texts(200)[-1])

    def test_user_callback_ignored(self):
        # Не-модератор нажал старую/поддельную кнопку — заявка не создаётся
        self.users.handle(make_update(
            "message_callback", 200, "", callback_id="x", callback_data="mod:close:1"))
        self.assertEqual(self.api.to(200), [])
        self.assertEqual(self.tickets.get_all(), [])


# --- Тесты модератора: команды ---

class TestModCommands(BaseTest):
    def test_mod_opens_menu(self):
        self.say("/mod")
        msg = self.api.to(100)[0]
        self.assertIn("Меню модератора", msg.text)
        payloads = [b["payload"] for row in msg.buttons for b in row]
        self.assertIn("mod:list", payloads)
        self.assertIn("mod:mods", payloads)

    def test_menu_button_opens_menu(self):
        self.say("🛠 Меню")
        self.assertIn("Меню модератора", self.api.texts(100)[0])

    def test_start_shows_logo_for_moderator(self):
        self.say("/start")
        self.assertIn("ИТМеханизатор — Support", self.api.photos[0][2])
        self.assertIn("модератора", self.api.photos[0][2])

    def test_unknown_text_shows_menu(self):
        self.say("абракадабра")
        self.assertIn("Не понял сообщение", self.api.texts(100)[0])
        self.assertIsNotNone(self.api.to(100)[0].buttons)

    def test_list_empty(self):
        self.press("mod:list")
        self.assertIn("Открытых заявок нет", self.api.texts(100)[0])

    def test_list_shows_tickets_with_buttons(self):
        self.say("проблема А", user_id=200)
        self.api.sent.clear()
        self.press("mod:list")
        self.assertIn("Открытые заявки: 1", self.api.texts(100)[0])
        ticket_msg = self.api.to(100)[1]
        self.assertIn("проблема А", ticket_msg.text)
        self.assertEqual(ticket_msg.buttons[0][0]["payload"], "mod:answer:1")


# --- Тесты модератора: кнопки ---

class TestModButtons(BaseTest):
    def setUp(self):
        super().setUp()
        self.say("проблема А", user_id=200)  # заявка #1 от пользователя 200
        self.api.sent.clear()

    def test_answer_flow(self):
        self.press("mod:answer:1")
        self.assertIn("Напишите ответ по заявке #1", self.api.texts(100)[0])
        self.say("вот решение")
        self.assertIn("Ответ поддержки по заявке #1", self.api.texts(200)[0])
        self.assertIn("вот решение", self.api.texts(200)[0])
        self.assertIn("Ответ отправлен", self.api.texts(100)[-1])

    def test_answer_on_closed_ticket(self):
        self.tickets.close(1)
        self.press("mod:answer:1")
        self.assertIn("не найдена или уже закрыта", self.api.texts(100)[0])

    def test_answer_text_on_closed_ticket_not_sent(self):
        # Режим ответа активен, но заявку закрыл другой модератор
        self.press("mod:answer:1")
        self.tickets.close(1)
        self.say("вот решение")
        self.assertIn("уже закрыта — ответ не отправлен", self.api.texts(100)[-1])
        self.assertEqual(self.api.to(200), [])

    def test_close_flow(self):
        self.press("mod:close:1")
        self.assertEqual(self.tickets.find_by_id(1).status, "CLOSED")
        self.assertIn("закрыта", self.api.texts(200)[0])
        self.assertIn("Заявка #1 закрыта", self.api.texts(100)[0])

    def test_double_close_no_duplicate_notice(self):
        self.press("mod:close:1")
        self.api.sent.clear()
        self.press("mod:close:1")
        self.assertIn("уже закрыта", self.api.texts(100)[0])
        # Автору не ушло повторное уведомление о закрытии
        self.assertEqual(self.api.to(200), [])

    def test_close_after_answer_button(self):
        self.press("mod:answer:1")
        self.say("вот решение")
        close_btn = self.api.to(100)[-1].buttons[0][0]["payload"]
        self.assertEqual(close_btn, "mod:close:1")
        self.press(close_btn)
        self.assertEqual(self.tickets.find_by_id(1).status, "CLOSED")

    def test_unknown_ticket(self):
        self.press("mod:close:99")
        self.assertIn("не найдена", self.api.texts(100)[0])

    def test_unknown_button(self):
        self.press("mod:nonsense")
        self.assertIn("Неизвестная кнопка", self.api.texts(100)[0])

    def test_malformed_callback_data_not_crash(self):
        self.press("mod:answer:abc")
        self.assertIn("Некорректная кнопка", self.api.texts(100)[0])
        self.press("mod:close:xyz")
        self.assertIn("Некорректная кнопка", self.api.texts(100)[1])

    def test_callback_is_answered(self):
        self.press("mod:list", cid="cb42")
        self.assertIn("cb42", self.api.callback_answers)

    def test_answer_pending_cancelled_by_menu(self):
        self.press("mod:answer:1")
        self.say("🛠 Меню")  # открыл меню вместо ответа
        self.assertIn("Меню модератора", self.api.texts(100)[-1])
        # Режим ответа сброшен: следующее сообщение — не ответ
        self.api.sent.clear()
        self.say("просто текст")
        self.assertIn("Не понял сообщение", self.api.texts(100)[0])
        self.assertEqual(self.api.to(200), [])

    def test_answer_cancelled_by_cancel_button(self):
        self.press("mod:answer:1")
        self.press("mod:cancel:1")
        self.assertIn("отменён", self.api.texts(100)[-1])
        self.api.sent.clear()
        self.say("просто текст")
        self.assertIn("Не понял сообщение", self.api.texts(100)[0])
        self.assertEqual(self.api.to(200), [])

    def test_answer_cancelled_by_cancel_command(self):
        self.press("mod:answer:1")
        self.say("/cancel")
        self.assertIn("Меню модератора", self.api.texts(100)[-1])
        self.api.sent.clear()
        self.say("просто текст")
        self.assertEqual(self.api.to(200), [])

    def test_answer_prompt_has_cancel_button(self):
        self.press("mod:answer:1")
        prompt = self.api.to(100)[0]
        self.assertEqual(prompt.buttons[0][0]["payload"], "mod:cancel:1")


# --- Тесты модераторов: добавление/удаление ---

class TestModeratorManagement(BaseTest):
    def test_mods_list_with_buttons(self):
        self.press("mod:mods")
        texts = self.api.texts(100)
        self.assertIn("Модераторы", texts[0])
        self.assertIn("100", texts[1])
        add_msg = self.api.to(100)[-1]
        self.assertEqual(add_msg.buttons[0][0]["payload"], "mod:add")

    def test_add_moderator_flow(self):
        self.press("mod:add")
        self.assertIn("ID пользователя MAX", self.api.texts(100)[0])
        self.say("300")
        self.assertIn("Модератор 300 добавлен", self.api.texts(100)[-1])
        self.assertTrue(self.moderators.is_moderator(300))

    def test_add_moderator_invalid_id_retries(self):
        self.press("mod:add")
        self.say("абракадабра")
        self.assertIn("ID должен быть числом", self.api.texts(100)[-1])
        self.say("400")
        self.assertIn("Модератор 400 добавлен", self.api.texts(100)[-1])

    def test_add_negative_moderator_rejected(self):
        self.press("mod:add")
        self.say("-999")
        self.assertIn("положительным числом", self.api.texts(100)[-1])
        self.assertEqual(self.moderators.get_all(), [100])

    def test_add_duplicate_moderator(self):
        self.press("mod:add")
        self.say("100")
        self.assertIn("уже модератор", self.api.texts(100)[-1])

    def test_remove_moderator(self):
        self.moderators.add(300)
        self.press("mod:remove:300")
        self.assertIn("Модератор 300 удалён", self.api.texts(100)[0])
        self.assertFalse(self.moderators.is_moderator(300))

    def test_remove_non_moderator(self):
        self.moderators.add(300)
        self.press("mod:remove:999")
        self.assertIn("не является модератором", self.api.texts(100)[0])

    def test_remove_last_moderator_forbidden(self):
        self.press("mod:remove:100")
        self.assertIn("последнего модератора", self.api.texts(100)[0])
        self.assertTrue(self.moderators.is_moderator(100))

    def test_remove_ok_when_two_mods(self):
        self.moderators.add(300)
        self.press("mod:remove:100")
        self.assertIn("Модератор 100 удалён", self.api.texts(100)[0])
        self.assertEqual(self.moderators.get_all(), [300])


# --- Тесты заявок ---

class TestTicketService(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = FakeConfig(Path(self.tmp.name))
        self.svc = TicketService(self.config)

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_and_ids_increment(self):
        t1 = self.svc.create(1, "А", "текст1")
        t2 = self.svc.create(2, "Б", "текст2")
        self.assertEqual((t1.id, t2.id), (1, 2))
        self.assertEqual(t1.status, "NEW")

    def test_persistence(self):
        self.svc.create(1, "А", "текст1")
        svc2 = TicketService(self.config)
        self.assertEqual(svc2.find_by_id(1).text, "текст1")

    def test_close_and_find_new(self):
        self.svc.create(1, "А", "текст1")
        self.svc.create(2, "Б", "текст2")
        self.svc.close(1)
        self.assertEqual([t.id for t in self.svc.find_new()], [2])
        self.svc.close(99)  # не падает


# --- Тесты MaxApi (без сети) ---

class TestMaxApiParsing(unittest.TestCase):
    """Парсинг GET /updates и формирование запросов."""

    def _api(self):
        api = MaxApi.__new__(MaxApi)
        api._token = "TEST"
        api._base_url = "https://platform-api2.max.ru"
        api._last_send = {}
        api._ssl_context = ssl.create_default_context()
        return api

    def _parse(self, payload):
        api = self._api()
        with patch.object(api, "_send_get", return_value=payload):
            return api.get_updates(None)

    def test_message_created_parsing(self):
        updates, marker = self._parse({
            "updates": [{
                "update_type": "message_created",
                "timestamp": 1,
                "message": {
                    "sender": {"user_id": 20, "name": "Иван"},
                    "recipient": {"chat_id": 10},
                    "body": {"text": "привет"},
                },
            }],
            "marker": 5,
        })
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].user_id, 20)
        self.assertEqual(updates[0].text, "привет")
        self.assertEqual(marker, 5)

    def test_message_callback_parsing(self):
        # Нажавший кнопку лежит в callback.user (реальная структура из логов MAX),
        # message.sender — это сам бот
        updates, _ = self._parse({
            "updates": [{
                "update_type": "message_callback",
                "timestamp": 2,
                "callback": {
                    "callback_id": "cb1",
                    "payload": "mod:list",
                    "user": {"user_id": 30, "name": "Мод", "is_bot": False},
                    "message": {
                        "recipient": {"chat_id": 30, "chat_type": "dialog", "user_id": 30},
                        "body": {"text": "старое"},
                        "sender": {"user_id": 999, "name": "SmartBot", "is_bot": True},
                    },
                },
            }],
            "marker": 6,
        })
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].callback_id, "cb1")
        self.assertEqual(updates[0].callback_data, "mod:list")
        self.assertEqual(updates[0].user_id, 30)
        self.assertEqual(updates[0].user_name, "Мод")

    def test_message_callback_without_message(self):
        # callback.message может не прийти — адрес берём из user_id нажавшего
        updates, _ = self._parse({
            "updates": [{
                "update_type": "message_callback",
                "timestamp": 2,
                "callback": {
                    "callback_id": "cb3",
                    "payload": "mod:list",
                    "user": {"user_id": 32, "name": "Мод3", "is_bot": False},
                },
            }],
            "marker": 6,
        })
        self.assertEqual(updates[0].user_id, 32)
        self.assertEqual(updates[0].callback_id, "cb3")

    def test_message_callback_fallback_sender(self):
        # Запасной вариант: sender внутри callback.sender
        updates, _ = self._parse({
            "updates": [{
                "update_type": "message_callback",
                "timestamp": 2,
                "callback": {
                    "callback_id": "cb2",
                    "payload": "mod:list",
                    "sender": {"user_id": 31, "name": "Мод2"},
                    "message": {
                        "recipient": {"chat_id": 31},
                        "body": {"text": "старое"},
                    },
                },
            }],
            "marker": 6,
        })
        self.assertEqual(updates[0].user_id, 31)
        self.assertEqual(updates[0].callback_id, "cb2")

    def test_bot_started_becomes_start(self):
        updates, _ = self._parse({
            "updates": [{
                "update_type": "bot_started",
                "timestamp": 3,
                "user": {"user_id": 40, "name": "Новый"},
            }],
            "marker": 7,
        })
        self.assertEqual(updates[0].text, "/start")
        self.assertEqual(updates[0].user_id, 40)

    def test_other_updates_skipped(self):
        updates, _ = self._parse({
            "updates": [{"update_type": "dialog_muted", "timestamp": 4}],
            "marker": 8,
        })
        self.assertEqual(updates, [])

    def test_send_message_body(self):
        api = self._api()
        posts = []

        def fake_post(path, body):
            posts.append((path, body))
            return {}

        with patch.object(api, "_send_post", side_effect=fake_post):
            api.send_message(5, "текст", buttons=[
                [{"type": "callback", "text": "b", "payload": "x"}],
            ])
        path, body = posts[0]
        self.assertTrue(path.startswith("/messages?user_id=5"))
        att = body["attachments"][0]
        self.assertEqual(att["type"], "inline_keyboard")
        self.assertEqual(att["payload"]["buttons"][0][0]["payload"], "x")

    def test_long_text_truncated(self):
        api = self._api()
        with patch.object(api, "_send_post", return_value={}) as p:
            api.send_message(5, "а" * 5000)
        body = p.call_args[0][1]
        self.assertLessEqual(len(body["text"]), 4022)
        self.assertIn("обрезано", body["text"])

    def test_send_photo_uploads_first(self):
        api = self._api()
        uploads = []
        posts = []

        def fake_post(path, body):
            if path.startswith("/uploads"):
                uploads.append(path)
                return {"url": "http://upload.example"}
            posts.append((path, body))
            return {}

        with patch.object(api, "_send_post", side_effect=fake_post), \
             patch.object(api, "_upload_image", return_value="TOKEN123"):
            api.send_photo(9, Path("assets/logo.png"), "Логотип")
        path, body = posts[0]
        self.assertEqual(body["text"], "Логотип")
        self.assertEqual(body["attachments"][0]["payload"]["token"], "TOKEN123")

    def test_answer_callback_body(self):
        api = self._api()
        with patch.object(api, "_send_post", return_value={}) as p:
            api.answer_callback("cb9")
        path, body = p.call_args[0]
        self.assertEqual(path, "/answers?callback_id=cb9")
        # Без message обязательно отправляем notification
        self.assertEqual(body["notification"], "Ок")

    def test_answer_callback_with_message(self):
        api = self._api()
        with patch.object(api, "_send_post", return_value={}) as p:
            api.answer_callback("cb9", message={"text": "новый текст"})
        body = p.call_args[0][1]
        self.assertEqual(body["message"]["text"], "новый текст")

    def test_set_commands(self):
        api = self._api()
        with patch.object(api, "_send_patch", return_value={}) as p:
            api.set_my_commands([("start", "Привет")])
        body = p.call_args[0][1]
        self.assertEqual(body["commands"][0]["name"], "start")

    def test_authorization_header_used(self):
        api = self._api()
        api._token = "SECRET"
        with patch("bot.max_api.urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b"{}"
            api._send_get("/updates")
        req = urlopen.call_args[0][0]
        self.assertEqual(req.headers.get("Authorization"), "SECRET")
        self.assertNotIn("SECRET", req.full_url)

    def test_http_error_returns_empty_dict(self):
        import urllib.error
        api = self._api()
        with patch("bot.max_api.urllib.request.urlopen") as urlopen:
            urlopen.side_effect = urllib.error.HTTPError(
                "url", 500, "Server Error", {}, io.BytesIO(b'{"code":"server"}'))
            result = api._send_get("/updates")
        self.assertEqual(result, {})

    def test_auth_error_raised_on_401(self):
        import urllib.error
        from bot.max_api import AuthError
        api = self._api()
        with patch("bot.max_api.urllib.request.urlopen") as urlopen:
            urlopen.side_effect = urllib.error.HTTPError(
                "url", 401, "Unauthorized", {}, io.BytesIO(b'{"code":"auth"}'))
            with self.assertRaises(AuthError):
                api._send_get("/updates")

    def test_bot_run_stops_on_auth_error(self):
        # При невалидном токене бот останавливается, а не ретраит вечно
        from bot.bot import Bot
        from bot.max_api import AuthError
        bot = Bot.__new__(Bot)
        bot._api = self._api()
        bot._moderators = None
        calls = {"n": 0}

        def fail(marker):
            calls["n"] += 1
            raise AuthError("токен отклонён")

        bot._get_updates = fail
        with self.assertRaises(SystemExit):
            bot.run()
        self.assertEqual(calls["n"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
