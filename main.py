import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher

from config.config import settings
from handlers.common import common_router
from handlers.order import order_router
from services.google_sheets import sheets_service
from services.pickup_reminder_worker import run_pickup_reminder_worker


logging.basicConfig(level=logging.INFO)


async def main() -> None:
	bot = Bot(token=settings.bot_token.get_secret_value())
	dp = Dispatcher()
	dp.include_routers(common_router, order_router)
	reminder_task = None

	if not await sheets_service.test_connection():
		logging.error("Google Sheets connection test failed. Exiting application.")
		await bot.session.close()
		return

	try:
		await sheets_service.ensure_order_schema()
	except Exception:
		logging.exception("Failed to initialize Google Sheets order schema. Exiting application.")
		await bot.session.close()
		return

	reminder_task = asyncio.create_task(run_pickup_reminder_worker(bot))

	try:
		await dp.start_polling(bot)
	finally:
		if reminder_task is not None:
			reminder_task.cancel()
			with contextlib.suppress(asyncio.CancelledError):
				await reminder_task
		await bot.session.close()


if __name__ == "__main__":
	asyncio.run(main())
