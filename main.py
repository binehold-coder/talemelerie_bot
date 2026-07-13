import asyncio
import logging

from aiogram import Bot, Dispatcher

from config.config import settings
from handlers.common import common_router
from handlers.order import order_router
from services.google_sheets import sheets_service


logging.basicConfig(level=logging.INFO)


async def main() -> None:
	bot = Bot(token=settings.bot_token.get_secret_value())
	dp = Dispatcher()
	dp.include_routers(common_router, order_router)

	if not await sheets_service.test_connection():
		logging.error("Google Sheets connection test failed. Exiting application.")
		await bot.session.close()
		return

	try:
		await dp.start_polling(bot)
	finally:
		await bot.session.close()


if __name__ == "__main__":
	asyncio.run(main())
