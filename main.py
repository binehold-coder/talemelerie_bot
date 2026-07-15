import asyncio
import contextlib
import logging
import signal

from aiogram import Bot, Dispatcher

from config.config import settings
from handlers.common import common_router
from handlers.order import order_router
from services.google_sheets import sheets_service
from services.pickup_reminder_worker import run_pickup_reminder_worker


logging.basicConfig(level=logging.INFO)


async def shutdown(bot: Bot, dp: Dispatcher, reminder_task: asyncio.Task | None) -> None:
	# Stop polling, stop the reminder worker, and close the bot session cleanly.
	logging.info("Shutdown initiated")

	with contextlib.suppress(RuntimeError):
		await dp.stop_polling()

	if reminder_task is not None and not reminder_task.done():
		reminder_task.cancel()
		try:
			await asyncio.wait_for(reminder_task, timeout=5)
		except asyncio.TimeoutError:
			logging.warning("Reminder worker did not stop within 5 seconds; forcing cancellation")
			reminder_task.cancel()
			with contextlib.suppress(asyncio.CancelledError):
				await reminder_task
		except asyncio.CancelledError:
			pass
		except Exception:
			logging.exception("Reminder worker failed during shutdown")

	with contextlib.suppress(Exception):
		await bot.session.close()


async def main() -> None:
	bot = Bot(token=settings.bot_token.get_secret_value())
	dp = Dispatcher()
	dp.include_routers(common_router, order_router)
	reminder_task: asyncio.Task | None = None
	shutdown_task: asyncio.Task | None = None
	shutdown_started = asyncio.Event()

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

	try:
		await sheets_service.setup_sheets()
	except Exception:
		logging.exception("Failed to set up Google Sheets tabs and validation. Continuing startup.")

	reminder_task = asyncio.create_task(run_pickup_reminder_worker(bot))
	loop = asyncio.get_running_loop()

	def _request_shutdown() -> None:
		nonlocal shutdown_task
		if shutdown_started.is_set():
			return

		shutdown_started.set()
		shutdown_task = asyncio.create_task(shutdown(bot, dp, reminder_task))

	for sig in (signal.SIGINT, signal.SIGTERM):
		try:
			loop.add_signal_handler(sig, _request_shutdown)
		except NotImplementedError:
			logging.warning("Signal handlers are not supported on this platform for %s", sig.name)

	try:
		await dp.start_polling(bot, handle_signals=False, close_bot_session=False)
	finally:
		if shutdown_task is None:
			await shutdown(bot, dp, reminder_task)
		else:
			with contextlib.suppress(asyncio.CancelledError):
				await shutdown_task


if __name__ == "__main__":
	asyncio.run(main())
