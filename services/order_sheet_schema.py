from typing import Any


COL_CREATED_AT = "Date Commande"
COL_CUSTOMER_NAME = "Client"
COL_PHONE = "Téléphone"
COL_PICKUP_DATETIME = "Retrait prévu"
COL_ORDER_DETAILS = "Commande (Détails)"
COL_TOTAL = "Total (€)"
COL_TELEGRAM_CHAT_ID = "Chat ID"
COL_REMINDER_SENT_AT = "Rappel envoyé le"
COL_ORDER_ID = "Order ID"
COL_STATUS = "Statut"
COL_STATUS_UPDATED_AT = "Statut mis à jour le"
COL_READY_NOTIFICATION_SENT_AT = "Notification prêt envoyée le"
COL_COLLECTED_AT = "Retiré le"
COL_CANCELLED_AT = "Annulé le"
COL_CANCELLATION_REASON = "Motif d’annulation"

ORDER_SHEET_COLUMNS = [
	COL_ORDER_ID,
	COL_STATUS,
	COL_PICKUP_DATETIME,
	COL_CUSTOMER_NAME,
	COL_PHONE,
	COL_ORDER_DETAILS,
	COL_TOTAL,
	COL_CREATED_AT,
	COL_CANCELLATION_REASON,
	COL_STATUS_UPDATED_AT,
	COL_TELEGRAM_CHAT_ID,
	COL_REMINDER_SENT_AT,
	COL_READY_NOTIFICATION_SENT_AT,
	COL_COLLECTED_AT,
	COL_CANCELLED_AT,
]

COLUMN_INDEX = {name: index for index, name in enumerate(ORDER_SHEET_COLUMNS)}


def column_1based(name: str) -> int:
	return COLUMN_INDEX[name] + 1


def build_order_row(values: dict[str, Any]) -> list[Any]:
	row = [""] * len(ORDER_SHEET_COLUMNS)
	for name, value in values.items():
		if name in COLUMN_INDEX:
			row[COLUMN_INDEX[name]] = value
	return row


def get_row_value(row: list[str], column_name: str) -> str:
	index = COLUMN_INDEX[column_name]
	if index >= len(row):
		return ""
	value = row[index]
	return value if value is not None else ""