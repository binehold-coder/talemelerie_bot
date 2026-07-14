import json
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import F, Router, types
from aiogram.enums import ContentType

from services.google_sheets import sheets_service
from services.order_sheet_schema import (
	COL_CANCELLATION_REASON,
	COL_CANCELLED_AT,
	COL_COLLECTED_AT,
	COL_CREATED_AT,
	COL_CUSTOMER_NAME,
	COL_ORDER_DETAILS,
	COL_PHONE,
	COL_PICKUP_DATETIME,
	COL_READY_NOTIFICATION_SENT_AT,
	COL_REMINDER_SENT_AT,
	COL_STATUS,
	COL_STATUS_UPDATED_AT,
	COL_TELEGRAM_CHAT_ID,
	COL_TOTAL,
)


order_router = Router()
PARIS_TZ = ZoneInfo("Europe/Paris")


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
		quantity_raw = raw_item.get("quantity") or raw_item.get("qty") or raw_item.get("count") or 1
		try:
			quantity = int(quantity_raw)
		except (TypeError, ValueError):
			quantity = 1

		unit_price = _coerce_amount(
			raw_item.get("unit_price")
			or raw_item.get("unitPrice")
			or raw_item.get("price")
		)
		line_total = _coerce_amount(
			raw_item.get("line_total")
			or raw_item.get("lineTotal")
			or raw_item.get("total")
		)

		if unit_price is None and line_total is not None and quantity:
			unit_price = (line_total / Decimal(quantity)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
		if line_total is None and unit_price is not None:
			line_total = (unit_price * Decimal(quantity)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

		if unit_price is None or line_total is None:
			item_text = f"{name} x {quantity}"
		else:
			item_text = (
				f"{name} x {quantity} "
				f"({_format_money(unit_price)} x {quantity} = {_format_money(line_total)})"
			)

		formatted_items.append(item_text)

	return ", ".join(formatted_items) if formatted_items else "N/A"


def _coerce_amount(value: Any) -> Decimal | None:
	if value in (None, ""):
		return None

	try:
		amount = Decimal(str(value).replace(",", "."))
	except (InvalidOperation, ValueError, TypeError):
		return None

	return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _format_money(value: Any) -> str:
	amount = _coerce_amount(value)
	if amount is None:
		return "N/A"

	return f"{amount:.2f}".replace(".", ",") + " €"


def _format_total(total_value: Any) -> float | None:
	amount = _coerce_amount(total_value)
	if amount is None:
		return None

	return float(amount)


def _format_pickup_datetime(value: str) -> str:
	"""Convert an HTML datetime-local value to the format used in the order sheet."""
	try:
		pickup_datetime = datetime.fromisoformat(value)
	except ValueError:
		logging.warning("Could not parse pickup datetime: %r", value)
		return value

	return pickup_datetime.strftime("%Hh%M %d-%m-%Y")


def _now_paris() -> datetime:
	return datetime.now(PARIS_TZ)


def _format_display_datetime(value: datetime) -> str:
	return value.strftime("%Hh%M %d-%m-%Y")


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
		pickup_datetime = _format_pickup_datetime(pickup_datetime_full)
	elif pickup_date and pickup_time:
		pickup_datetime = _format_pickup_datetime(f"{pickup_date} {pickup_time}")
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

	created_at = _now_paris()
	created_at_display = _format_display_datetime(created_at)
	row_values = {
		COL_CREATED_AT: created_at_display,
		COL_CUSTOMER_NAME: name,
		COL_PHONE: phone,
		COL_PICKUP_DATETIME: pickup_datetime,
		COL_ORDER_DETAILS: items_details,
		COL_TOTAL: total_price if total_price is not None else "",
		COL_TELEGRAM_CHAT_ID: message.chat.id,
		COL_REMINDER_SENT_AT: "",
		COL_STATUS: "Nouveau",
		COL_STATUS_UPDATED_AT: created_at_display,
		COL_READY_NOTIFICATION_SENT_AT: "",
		COL_COLLECTED_AT: "",
		COL_CANCELLED_AT: "",
		COL_CANCELLATION_REASON: "",
	}

	try:
		order_id = await sheets_service.append_order_with_sequential_id(row_values, created_at)
		logging.info("Order saved to Google Sheets successfully with order_id=%s", order_id)
	except Exception:
		logging.exception("Failed to save order to Google Sheets")
		await message.answer(
			"Votre commande a ete recue, mais l'enregistrement a echoue. Veuillez reessayer dans quelques instants."
		)
		return

	await message.answer("Merci pour votre commande ! Nous la preparons deja...")
