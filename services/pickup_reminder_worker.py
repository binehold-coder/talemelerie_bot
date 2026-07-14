import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot

from services.google_sheets import sheets_service


REMINDER_LEAD_MINUTES = 1
PARIS_TZ = ZoneInfo("Europe/Paris")


def _parse_pickup_datetime(value: str) -> datetime | None:
	try:
		return datetime.strptime(value.strip(), "%Hh%M %d-%m-%Y").replace(tzinfo=PARIS_TZ)
	except (ValueError, AttributeError):
		return None


def _format_timestamp(value: datetime) -> str:
	return value.astimezone(PARIS_TZ).strftime("%Y-%m-%d %H:%M:%S")


async def _get_first_worksheet_rows() -> list[list[str]]:
	def _read_rows() -> list[list[str]]:
		worksheet = sheets_service.spreadsheet.get_worksheet(0)
		if worksheet is None:
			raise RuntimeError("The spreadsheet does not contain any worksheets")
		return worksheet.get_all_values()

	return await asyncio.to_thread(_read_rows)


async def _update_reminder_sent_at(row_number: int, timestamp: str) -> None:
	def _write_timestamp() -> None:
		worksheet = sheets_service.spreadsheet.get_worksheet(0)
		if worksheet is None:
			raise RuntimeError("The spreadsheet does not contain any worksheets")
		worksheet.update_cell(row_number, 8, timestamp)

	await asyncio.to_thread(_write_timestamp)


async def _process_reminders(bot: Bot) -> None:
	try:
		rows = await _get_first_worksheet_rows()
	except Exception:
		logging.exception("Error while reading Google Sheets for pickup reminders")
		return

	if len(rows) <= 1:
		return

	now = datetime.now(PARIS_TZ)

	for row_number, row in enumerate(rows[1:], start=2):
		try:
			if len(row) < 8:
				logging.info("Skipped invalid reminder row %s: missing reminder columns", row_number)
				continue

			customer_name = (row[1] or "").strip()
			pickup_value = (row[3] or "").strip()
			telegram_chat_id = (row[6] or "").strip()
			reminder_sent_at = (row[7] or "").strip()

			if not telegram_chat_id or reminder_sent_at:
				continue

			pickup_datetime = _parse_pickup_datetime(pickup_value)
			if pickup_datetime is None:
				logging.info("Skipped invalid reminder row %s: invalid pickup datetime %r", row_number, pickup_value)
				continue

			reminder_time = pickup_datetime - timedelta(minutes=REMINDER_LEAD_MINUTES)
			if not (reminder_time <= now < pickup_datetime):
				continue

			pickup_time_text = pickup_datetime.strftime("%Hh%M %d-%m-%Y")
			message_text = (
				f"Bonjour, {customer_name} ! Votre retrait est prévu dans une minute, à {pickup_time_text}. "
				"Nous vous attendons chez La Talemelerie ! 🥐"
			)

			chat_id = int(telegram_chat_id)
			await bot.send_message(chat_id=chat_id, text=message_text)
			await _update_reminder_sent_at(row_number, _format_timestamp(datetime.now(PARIS_TZ)))
			logging.info("Reminder sent successfully for row %s to chat_id %s", row_number, chat_id)
		except ValueError:
			logging.info("Skipped invalid reminder row %s: invalid telegram_chat_id %r", row_number, telegram_chat_id)
		except Exception:
			logging.exception("Error while processing reminder row %s", row_number)


async def run_pickup_reminder_worker(bot: Bot) -> None:
	logging.info("Pickup reminder worker started (lead time: %s minute(s))", REMINDER_LEAD_MINUTES)
	while True:
		await _process_reminders(bot)
		await asyncio.sleep(60)