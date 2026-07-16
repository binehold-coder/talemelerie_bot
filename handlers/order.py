import asyncio
import functools
import json
import logging
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import F, Router, types
from aiogram.enums import ContentType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config.config import settings
from keyboards.inline import order_cancel_inline_keyboard
from services.google_sheets import sheets_service
from services.order_sheet_schema import (
	COL_CANCELLATION_REASON,
	COL_CANCELLED_AT,
	COL_COLLECTED_AT,
	COL_CREATED_AT,
	COL_CUSTOMER_NAME,
	COL_ORDER_ID,
	COL_ORDER_DETAILS,
	COL_PHONE,
	COL_PICKUP_DATETIME,
	COL_READY_NOTIFICATION_SENT_AT,
	COL_REMINDER_SENT_AT,
	COL_STATUS,
	COL_STATUS_UPDATED_AT,
	COL_TELEGRAM_CHAT_ID,
	COL_TOTAL,
	get_row_value,
)


order_router = Router()
PARIS_TZ = ZoneInfo("Europe/Paris")
MAX_PICKUP_DAYS_AHEAD = 60
WEEKDAY_OPEN_TIME = (6, 30)
WEEKDAY_CLOSE_TIME = (19, 30)
SUNDAY_OPEN_TIME = (6, 30)
SUNDAY_CLOSE_TIME = (13, 0)


class CancelOrderState(StatesGroup):
	waiting_order_id = State()


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


# In-memory anti-duplicate guard for a single bot instance.
_last_order_time: dict[int, datetime] = {}
TEMP_DISABLE_DUPLICATE_GUARD = True


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


def parse_pickup_datetime(value: str) -> str:
	# Parse multiple expected user/webapp date-time formats and normalize for Sheets.
	if value is None:
		raise ValueError("La date et l'heure de retrait sont requises.")

	raw_value = str(value).strip()
	if not raw_value:
		raise ValueError("La date et l'heure de retrait sont requises.")

	normalized_value = raw_value.replace("h", ":")
	candidates: list[str] = [
		normalized_value,
		normalized_value.replace("T", " "),
	]

	patterns = [
		"%Y-%m-%d %H:%M:%S",
		"%Y-%m-%d %H:%M",
		"%d-%m-%Y %H:%M",
		"%d/%m/%Y %H:%M",
	]

	parsed_datetime: datetime | None = None
	for candidate in candidates:
		try:
			parsed_datetime = datetime.fromisoformat(candidate)
			break
		except ValueError:
			for pattern in patterns:
				try:
					parsed_datetime = datetime.strptime(candidate, pattern)
					break
				except ValueError:
					continue
			if parsed_datetime is not None:
				break

	if parsed_datetime is None:
		raise ValueError("La date/heure de retrait est invalide. Format attendu: YYYY-MM-DD HH:MM.")

	return parsed_datetime.strftime("%Hh%M %d-%m-%Y")


def _parse_pickup_datetime_to_paris(value: str) -> datetime:
	pickup_datetime = datetime.strptime(value, "%Hh%M %d-%m-%Y")
	return pickup_datetime.replace(tzinfo=PARIS_TZ)


def _pickup_contact_phone() -> str:
	phone = settings.bakery_phone.strip()
	return phone or "+33 X XX XX XX XX"


def _cancel_fallback_message() -> str:
	return (
		"Votre commande ne peut plus être annulée automatiquement, car sa préparation peut déjà avoir commencé.\n"
		"Pour toute demande, appelez-nous :\n"
		f"📞 {_pickup_contact_phone()}"
	)


def _normalized_order_id(value: str) -> str:
	return value.strip().upper()


async def _find_order_by_id(order_id: str) -> tuple[int, list[str]] | None:
	rows = await sheets_service.get_all_rows()
	target = _normalized_order_id(order_id)
	for row_number, row in enumerate(rows[1:], start=2):
		stored_order_id = _normalized_order_id(get_row_value(row, COL_ORDER_ID))
		if stored_order_id == target:
			return row_number, row
	return None


async def _cancel_order_in_sheet(order_id: str) -> bool:
	now_display = _format_display_datetime(_now_paris())
	return await sheets_service.update_order_status(
		order_id,
		"Annulé",
		status_updated_at=now_display,
		cancelled_at=now_display,
		cancellation_reason="Annulé par le client",
	)


async def _process_cancel_request(message: types.Message, chat_id: int, order_id: str) -> None:
	if not order_id.strip():
		await message.answer("Veuillez saisir un numéro de commande valide.")
		return

	found = await _find_order_by_id(order_id)
	if found is None:
		await message.answer("Aucune commande trouvée pour ce numéro.")
		return

	_, row = found
	stored_chat_id = get_row_value(row, COL_TELEGRAM_CHAT_ID).strip()
	if stored_chat_id != str(chat_id):
		await message.answer("Cette commande ne vous appartient pas.")
		return

	status = get_row_value(row, COL_STATUS).strip()
	if status != "Nouveau":
		await message.answer(_cancel_fallback_message())
		return

	stored_order_id = get_row_value(row, COL_ORDER_ID).strip()
	was_updated = await _cancel_order_in_sheet(stored_order_id)
	if not was_updated:
		await message.answer("❌ Impossible d'annuler la commande pour le moment. Veuillez réessayer.")
		return

	await message.answer("✅ Votre commande a bien été annulée.")


def is_valid_pickup_time(pickup_time: datetime) -> tuple[bool, str]:
	now = _now_paris()
	max_allowed = now + timedelta(days=MAX_PICKUP_DAYS_AHEAD)
	if pickup_time > max_allowed:
		return (
			False,
			(
				"Pour les commandes au-delà de 60 jours, veuillez nous contacter directement :\n"
				f"📞 {_pickup_contact_phone()}"
			),
		)

	weekday = pickup_time.weekday()
	if weekday == 6:  # Sunday
		open_hour, open_minute = SUNDAY_OPEN_TIME
		close_hour, close_minute = SUNDAY_CLOSE_TIME
	else:
		open_hour, open_minute = WEEKDAY_OPEN_TIME
		close_hour, close_minute = WEEKDAY_CLOSE_TIME

	pickup_minutes = pickup_time.hour * 60 + pickup_time.minute
	open_minutes = open_hour * 60 + open_minute
	close_minutes = close_hour * 60 + close_minute
	if pickup_minutes < open_minutes or pickup_minutes > close_minutes:
		return (
			False,
			"Nos horaires de retrait sont :\nLun–Sam 06:30–19:30, Dim 06:30–13:00",
		)

	return True, ""


def _extract_items(payload: dict[str, Any]) -> list[Any]:
	items = payload.get("items")
	if items is None:
		items = payload.get("cart")

	if not isinstance(items, list) or not items:
		raise ValueError("La liste des articles est vide ou invalide.")

	return items


def _calculate_total_from_items(items: list[Any]) -> Decimal:
	# Derive a reliable total from line or unit prices with quantity fallback.
	total = Decimal("0.00")
	for raw_item in items:
		if not isinstance(raw_item, dict):
			raise ValueError("Le format des articles est invalide.")

		quantity_raw = raw_item.get("quantity") or raw_item.get("qty") or raw_item.get("count") or 1
		try:
			quantity = int(quantity_raw)
		except (TypeError, ValueError):
			raise ValueError("La quantité d'un article est invalide.")

		if quantity <= 0:
			raise ValueError("La quantité d'un article doit être supérieure à 0.")

		line_total = _coerce_amount(
			raw_item.get("line_total")
			or raw_item.get("lineTotal")
			or raw_item.get("total")
		)
		unit_price = _coerce_amount(
			raw_item.get("unit_price")
			or raw_item.get("unitPrice")
			or raw_item.get("price")
		)

		if line_total is None and unit_price is None:
			raise ValueError("Le prix d'un article est manquant ou invalide.")

		if line_total is None:
			line_total = (unit_price * Decimal(quantity)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

		total += line_total

	return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def validate_order_payload(payload: dict) -> dict:
	# Validate required fields and return normalized values for persistence.
	if not isinstance(payload, dict):
		raise ValueError("Le format des données de commande est invalide.")

	name = _pick_first(payload, ["name", "userName", "customer_name"], default="")
	if not name:
		raise ValueError("Le nom du client est requis.")

	phone = _pick_first(payload, ["phone", "userPhone", "customer_phone"], default="")
	if not phone:
		raise ValueError("Le numéro de téléphone est requis.")

	sanitized_phone = re.sub(r"[\s\-().]", "", phone)
	if not re.fullmatch(r"\+?[0-9]{8,15}", sanitized_phone):
		raise ValueError("Le numéro de téléphone est invalide.")

	pickup_datetime_value = _pick_first(payload, ["pickup_datetime"], default="")
	if pickup_datetime_value:
		pickup_datetime = parse_pickup_datetime(pickup_datetime_value)
	else:
		pickup_date = _pick_first(payload, ["date", "deliveryDate"], default="")
		pickup_time = _pick_first(payload, ["time", "deliveryTime"], default="")
		if not pickup_date or not pickup_time:
			raise ValueError("La date et l'heure de retrait sont requises.")
		pickup_datetime = parse_pickup_datetime(f"{pickup_date} {pickup_time}")

	pickup_datetime_paris = _parse_pickup_datetime_to_paris(pickup_datetime)
	is_valid, pickup_error = is_valid_pickup_time(pickup_datetime_paris)
	if not is_valid:
		raise ValueError(pickup_error)

	items = _extract_items(payload)
	items_details = _format_items(items)
	if items_details == "N/A":
		raise ValueError("La liste des articles est invalide.")

	total_raw = payload.get("total")
	if total_raw is None:
		total_raw = payload.get("totalPrice")
	if total_raw is None:
		total_raw = payload.get("total_price")

	total_amount = _coerce_amount(total_raw)
	if total_amount is None:
		total_amount = _calculate_total_from_items(items)

	created_at = _now_paris()

	return {
		"name": name,
		"phone": phone,
		"pickup_datetime": pickup_datetime,
		"items_details": items_details,
		"total_price": float(total_amount),
		"created_at": created_at,
	}


def _callable_name(func: Any) -> str:
	if isinstance(func, functools.partial):
		return getattr(func.func, "__name__", repr(func.func))
	return getattr(func, "__name__", repr(func))


async def retry_async(func, *args, max_retries: int = 3, delay: float = 1.0, **kwargs):
	# Retry transient async failures with exponential backoff.
	last_exception: Exception | None = None
	for attempt in range(1, max_retries + 1):
		try:
			return await func(*args, **kwargs)
		except Exception as exc:  # noqa: BLE001 - deliberate retry boundary
			last_exception = exc
			if attempt >= max_retries:
				break

			wait_seconds = delay * (2 ** (attempt - 1))
			logging.warning(
				"Retry attempt %s/%s for %s failed: %s. Next retry in %.1f seconds.",
				attempt,
				max_retries,
				_callable_name(func),
				exc,
				wait_seconds,
			)
			await asyncio.sleep(wait_seconds)

	if last_exception is not None:
		raise last_exception

	raise RuntimeError("Unexpected retry state without captured exception")


@order_router.message(F.content_type == ContentType.WEB_APP_DATA)
async def web_app_data_handler(message: types.Message) -> None:
	# Parse and validate incoming WebApp payload safely.
	if message.web_app_data is None:
		logging.error("Validation failure: web_app_data is missing for chat_id=%s", message.chat.id)
		await message.answer("❌ Les données de la commande sont introuvables.")
		return

	try:
		payload = json.loads(message.web_app_data.data)
	except json.JSONDecodeError:
		logging.exception("Validation failure: invalid JSON payload for chat_id=%s", message.chat.id)
		await message.answer("❌ Les données reçues sont invalides. Veuillez réessayer.")
		return

	if not isinstance(payload, dict):
		logging.error("Validation failure: payload is not an object for chat_id=%s", message.chat.id)
		await message.answer("❌ Les données reçues sont invalides. Veuillez réessayer.")
		return

	# Block accidental duplicate orders from the same chat within a 5-minute window.
	chat_id = message.chat.id
	now = _now_paris()
	if not TEMP_DISABLE_DUPLICATE_GUARD:
		last_order_at = _last_order_time.get(chat_id)
		if last_order_at is not None and now - last_order_at < timedelta(minutes=5):
			await message.answer("⏳ Vous avez déjà passé une commande récemment. Veuillez patienter 5 minutes.")
			return

	try:
		validated = validate_order_payload(payload)
	except ValueError as exc:
		logging.error("Validation failure for chat_id=%s: %s", chat_id, exc)
		await message.answer(f"❌ {exc}")
		return

	created_at = validated["created_at"]
	created_at_display = _format_display_datetime(created_at)
	row_values = {
		COL_CREATED_AT: created_at_display,
		COL_CUSTOMER_NAME: validated["name"],
		COL_PHONE: validated["phone"],
		COL_PICKUP_DATETIME: validated["pickup_datetime"],
		COL_ORDER_DETAILS: validated["items_details"],
		COL_TOTAL: validated["total_price"],
		COL_TELEGRAM_CHAT_ID: chat_id,
		COL_REMINDER_SENT_AT: "",
		COL_STATUS: "Nouveau",
		COL_STATUS_UPDATED_AT: created_at_display,
		COL_READY_NOTIFICATION_SENT_AT: "",
		COL_COLLECTED_AT: "",
		COL_CANCELLED_AT: "",
		COL_CANCELLATION_REASON: "",
	}

	# Persist order with retries for transient Google Sheets failures.
	try:
		order_id = await retry_async(
			sheets_service.append_order_with_sequential_id,
			row_values,
			created_at,
			max_retries=3,
			delay=1.0,
		)
	except Exception:
		logging.exception("Order persistence failed after retries for chat_id=%s", chat_id)
		await message.answer("❌ Le service est temporairement indisponible. Veuillez réessayer dans 5 minutes.")
		return

	if not TEMP_DISABLE_DUPLICATE_GUARD:
		_last_order_time[chat_id] = created_at
	logging.info("Order saved to Google Sheets successfully with order_id=%s for chat_id=%s", order_id, chat_id)
	await message.answer(
		f"✅ Merci pour votre commande ! Votre numéro de commande est {order_id}. Nous vous attendons à l'heure indiquée.",
		reply_markup=order_cancel_inline_keyboard(order_id),
	)


@order_router.message(Command("cancel_order"))
async def cancel_order_command_handler(message: types.Message, state: FSMContext) -> None:
	await state.set_state(CancelOrderState.waiting_order_id)
	await message.answer("Veuillez entrer votre numéro de commande (ex: LT-LMS-2026-07-001) :")


@order_router.message(CancelOrderState.waiting_order_id)
async def cancel_order_id_input_handler(message: types.Message, state: FSMContext) -> None:
	if message.text is None:
		await message.answer("Veuillez envoyer un numéro de commande en texte.")
		return

	await _process_cancel_request(message, message.chat.id, message.text)
	await state.clear()


@order_router.callback_query(F.data.startswith("cancel_order:"))
async def cancel_order_callback_handler(callback: types.CallbackQuery, state: FSMContext) -> None:
	if callback.message is None or not isinstance(callback.message, types.Message):
		await callback.answer()
		return

	order_id = callback.data.split(":", maxsplit=1)[1]
	await _process_cancel_request(callback.message, callback.from_user.id, order_id)
	await state.clear()
	await callback.answer()
