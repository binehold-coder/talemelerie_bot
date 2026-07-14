import json
import logging
from datetime import datetime
from typing import Any

from aiogram import F, Router, types
from aiogram.enums import ContentType

from services.google_sheets import sheets_service


order_router = Router()


@order_router.message(F.text == "📋 Passer une commande")
async def start_order_handler(message: types.Message) -> None:
	keyboard = types.ReplyKeyboardMarkup(
		keyboard=[
			[
				types.KeyboardButton(
					text="🚀 Ouvrir la boutique",
					web_app=types.WebAppInfo(url="https://talemelerie-bot-tcis.vercel.app"),
				),
			],
		],
		resize_keyboard=True,
	)
	await message.answer(
		"Veuillez ouvrir notre catalogue pour passer votre commande :",
		reply_markup=keyboard,
	)


def _pick_first(payload: dict[str, Any], keys: list[str], default: str = "N/A") -> str:
	for key in keys:
		value = payload.get(key)
		if value is None:
			continue
		as_text = str(value).strip()
		if as_text:
			return as_text
	return default


def _format_items(items_value: Any) -> str:
	if not isinstance(items_value, list) or not items_value:
		return "N/A"

	formatted_items: list[str] = []
	for raw_item in items_value:
		if not isinstance(raw_item, dict):
			formatted_items.append(str(raw_item))
			continue

		name = (
			str(
				raw_item.get("name")
				or raw_item.get("product")
				or raw_item.get("title")
				or "Article"
			)
			.strip()
		)
		quantity = raw_item.get("quantity") or raw_item.get("qty") or raw_item.get("count") or 1
		price = (
			raw_item.get("price")
			or raw_item.get("unitPrice")
			or raw_item.get("lineTotal")
			or raw_item.get("line_total")
		)

		item_text = f"{name} x{quantity}"
		if price not in (None, ""):
			item_text = f"{item_text} ({price}€)"

		formatted_items.append(item_text)

	return ", ".join(formatted_items) if formatted_items else "N/A"


def _format_total(total_value: Any) -> str:
	if total_value in (None, ""):
		return "N/A"

	total_text = str(total_value).strip()
	if not total_text:
		return "N/A"

	if "€" in total_text:
		return total_text
	return f"{total_text}€"


@order_router.message(F.content_type == ContentType.WEB_APP_DATA)
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

	name = _pick_first(payload, ["name", "userName", "customer_name"])
	phone = _pick_first(payload, ["phone", "userPhone", "customer_phone"])
	pickup_date = _pick_first(payload, ["date", "deliveryDate"], default="")
	pickup_time = _pick_first(payload, ["time", "deliveryTime"], default="")
	pickup_datetime_full = _pick_first(payload, ["pickup_datetime"], default="")

	if pickup_datetime_full:
		pickup_datetime = pickup_datetime_full
	elif pickup_date and pickup_time:
		pickup_datetime = f"{pickup_date} {pickup_time}"
	elif pickup_date:
		pickup_datetime = pickup_date
	elif pickup_time:
		pickup_datetime = pickup_time
	else:
		pickup_datetime = "N/A"

	items = payload.get("items")
	if items is None:
		items = payload.get("cart")
	items_details = _format_items(items)

	total_raw = payload.get("total")
	if total_raw is None:
		total_raw = payload.get("totalPrice")
	if total_raw is None:
		total_raw = payload.get("total_price")
	total_price = _format_total(total_raw)

	row_to_save = [
		datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
		name,
		phone,
		pickup_datetime,
		items_details,
		total_price,
	]

	try:
		logging.info("Saving order to Google Sheets: %s", row_to_save)
		await sheets_service.append_order(row_to_save)
		logging.info("Order saved to Google Sheets successfully")
	except Exception:
		logging.exception("Failed to save order to Google Sheets")
		await message.answer(
			"Votre commande a ete recue, mais l'enregistrement a echoue. Veuillez reessayer dans quelques instants."
		)
		return

	await message.answer("Merci pour votre commande ! Nous la preparons deja...")
