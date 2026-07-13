import json
import logging

from aiogram import F, Router, types

from services.google_sheets import sheets_service


order_router = Router()


@order_router.message(F.text == "📋 Passer une commande")
async def start_order_handler(message: types.Message) -> None:
	keyboard = types.InlineKeyboardMarkup(
		inline_keyboard=[
			[
				types.InlineKeyboardButton(
					text="🚀 Ouvrir la boutique",
					web_app=types.WebAppInfo(url="https://talemelerie-bot-tcis.vercel.app"),
				),
			],
		],
	)
	await message.answer(
		"Veuillez ouvrir notre catalogue pour passer votre commande :",
		reply_markup=keyboard,
	)


@order_router.message(F.content_type == types.ContentType.WEB_APP_DATA)
async def web_app_data_handler(message: types.Message) -> None:
	if message.web_app_data is None:
		await message.answer("Les données de la commande sont introuvables.")
		return

	try:
		payload = json.loads(message.web_app_data.data)
	except json.JSONDecodeError:
		logging.exception("Invalid Web App payload received")
		await message.answer("Les données reçues sont invalides. Veuillez réessayer.")
		return

	logging.info("Web App payload received: %s", payload)
	# TODO: Format data and save to Google Sheets via sheets_service
	_ = sheets_service
	await message.answer(
		"Merci ! Votre commande a bien été reçue. Nous la traitons maintenant."
	)
