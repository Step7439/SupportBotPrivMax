"""Бот техподдержки «ИТМеханизатор» для мессенджера MAX."""
from bot.bot import Bot
from bot.config import Config
from bot.max_api import MaxApi
from bot.moderator_service import ModeratorService
from bot.ticket_service import TicketService

__all__ = ["Bot", "Config", "MaxApi", "ModeratorService", "TicketService"]
