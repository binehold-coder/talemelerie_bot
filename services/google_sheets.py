import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import gspread
from gspread.exceptions import WorksheetNotFound
from gspread.utils import ValidationConditionType

from config.config import settings
from services.order_sheet_schema import COL_ORDER_ID, COL_STATUS, ORDER_SHEET_COLUMNS, build_order_row, column_1based


BASE_DIR = Path(__file__).resolve().parent.parent
ORDERS_WORKSHEET_TITLE = "Commandes"
CONFIG_WORKSHEET_TITLE = "Config"
PRODUCTION_WORKSHEET_TITLE = "Production"
ORDER_COUNTERS_WORKSHEET_TITLE = "Order Counters"
ORDER_COUNTERS_HEADERS = ["Prefix", "Last sequence"]
CONFIG_STATUSES = [
	"Nouveau",
	"En préparation",
	"Prêt",
	"Retiré",
	"Annulé",
]
PRODUCTION_ACTIVE_STATUSES = [
	"Nouveau",
	"En préparation",
	"Prêt",
]
HEADER_ALIASES = {
	"Nom": "Client",
	"Date/Heure Retrait": "Retrait prévu",
}
LEGACY_ORDER_SHEET_COLUMNS = [
	"Date Commande",
	"Client",
	"Téléphone",
	"Retrait prévu",
	"Commande (Détails)",
	"Total (€)",
	"Chat ID",
	"Rappel envoyé le",
	"Order ID",
	"Statut",
	"Statut mis à jour le",
	"Notification prêt envoyée le",
	"Retiré le",
	"Annulé le",
	"Motif d’annulation",
]


class GoogleSheetsService:
	def __init__(self) -> None:
		credentials_path = BASE_DIR / "credentials.json"
		if not credentials_path.exists():
			raise FileNotFoundError(
				f"Google service account credentials file not found: {credentials_path}"
			)

		if not settings.spreadsheet_id.strip():
			raise ValueError("SPREADSHEET_ID is empty")

		self.client = gspread.service_account(filename=str(credentials_path))
		self.spreadsheet = self.client.open_by_key(settings.spreadsheet_id)
		self._order_append_lock = asyncio.Lock()
		self._service_account_email = self.client.http_client.auth.service_account_email

	def _get_first_worksheet(self):
		try:
			return self.spreadsheet.worksheet(ORDERS_WORKSHEET_TITLE)
		except WorksheetNotFound:
			pass

		worksheet = self.spreadsheet.get_worksheet(0)
		if worksheet is None:
			raise RuntimeError("The spreadsheet does not contain any worksheets")
		return worksheet

	def _get_or_create_worksheet(self, title: str, rows: int = 1000, cols: int = 26):
		try:
			return self.spreadsheet.worksheet(title)
		except WorksheetNotFound:
			return self.spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)

	def _ensure_config_statuses(self, worksheet) -> str:
		status_values = [[status] for status in CONFIG_STATUSES]
		worksheet.update("A1:A5", status_values)
		return f"{CONFIG_WORKSHEET_TITLE}!A1:A{len(CONFIG_STATUSES)}"

	def _protect_worksheet(self, worksheet) -> None:
		protect = getattr(worksheet, "protect", None)
		if callable(protect):
			protect(editor_users_emails=[])
			return

		worksheet.add_protected_range(
			f"A1:{gspread.utils.rowcol_to_a1(worksheet.row_count, worksheet.col_count)}",
			editor_users_emails=[self._service_account_email],
			description=f"Protect {worksheet.title}",
		)

	def _set_data_validation_for_column(self, worksheet, column: int, source_range: str) -> None:
		set_validation = getattr(worksheet, "set_data_validation_for_column", None)
		if callable(set_validation):
			set_validation(column, source_range)
			return

		column_letter = gspread.utils.rowcol_to_a1(1, column).rstrip("1")
		worksheet.add_validation(
			f"{column_letter}2:{column_letter}",
			ValidationConditionType.one_of_range,
			[f"={source_range}"],
			strict=True,
			showCustomUi=True,
		)

	def _build_production_formula(self) -> str:
		status_column = gspread.utils.rowcol_to_a1(1, column_1based(COL_STATUS)).rstrip("1")
		conditions = " OR ".join(
			f"{status_column} = '{status}'"
			for status in PRODUCTION_ACTIVE_STATUSES
		)
		return f'=QUERY({ORDERS_WORKSHEET_TITLE}!A:O; "SELECT * WHERE {conditions}"; 1)'

	def _get_or_create_order_counters_worksheet(self):
		try:
			worksheet = self.spreadsheet.worksheet(ORDER_COUNTERS_WORKSHEET_TITLE)
		except WorksheetNotFound:
			worksheet = self.spreadsheet.add_worksheet(title=ORDER_COUNTERS_WORKSHEET_TITLE, rows=1000, cols=2)

		headers = worksheet.row_values(1)
		for column, expected_header in enumerate(ORDER_COUNTERS_HEADERS, start=1):
			current_header = headers[column - 1].strip() if column <= len(headers) else ""
			if current_header:
				continue
			worksheet.update_cell(1, column, expected_header)

		return worksheet

	def _normalized_bakery_code(self) -> str:
		code = settings.bakery_code.strip().upper()
		return code or "LMS"

	def _get_first_worksheet_title(self) -> str:
		worksheet = self._get_first_worksheet()
		return worksheet.title

	def _append_row(self, row_data: list) -> None:
		worksheet = self._get_first_worksheet()
		worksheet.append_row(row_data)

	def _get_all_rows(self) -> list[list[str]]:
		worksheet = self._get_first_worksheet()
		return worksheet.get_all_values()

	def _update_cell(self, row: int, column: int, value: str) -> None:
		worksheet = self._get_first_worksheet()
		worksheet.update_cell(row, column, value)

	def _ensure_order_schema(self) -> None:
		worksheet = self._get_first_worksheet()
		self._migrate_order_schema_if_needed(worksheet)

		self._get_or_create_order_counters_worksheet()

	def _setup_sheets(self) -> None:
		orders_worksheet = self._get_first_worksheet()
		config_worksheet = self._get_or_create_worksheet(CONFIG_WORKSHEET_TITLE, rows=1000, cols=1)
		production_worksheet = self._get_or_create_worksheet(PRODUCTION_WORKSHEET_TITLE)

		source_range = self._ensure_config_statuses(config_worksheet)
		status_column = column_1based(COL_STATUS)
		self._set_data_validation_for_column(orders_worksheet, status_column, source_range)
		production_worksheet.update_acell("A1", self._build_production_formula())
		self._protect_worksheet(config_worksheet)

	def _migrate_order_schema_if_needed(self, worksheet) -> None:
		rows = worksheet.get_all_values()
		headers = rows[0] if rows else []
		normalized_headers = [header.strip() for header in headers]
		canonical_headers = [HEADER_ALIASES.get(header, header) for header in normalized_headers]

		target_prefix_matches = all(
			(index < len(canonical_headers) and canonical_headers[index] == expected)
			for index, expected in enumerate(ORDER_SHEET_COLUMNS)
		)
		has_extra_non_empty_headers = any(
			header
			for header in canonical_headers[len(ORDER_SHEET_COLUMNS):]
		)
		target_matches = target_prefix_matches and not has_extra_non_empty_headers
		if target_matches:
			logging.info("Order schema migration skipped: worksheet already in target order")
			return

		legacy_matches = all(
			(index >= len(canonical_headers))
			or (not canonical_headers[index])
			or (canonical_headers[index] == LEGACY_ORDER_SHEET_COLUMNS[index])
			for index in range(len(LEGACY_ORDER_SHEET_COLUMNS))
		)
		if not legacy_matches:
			raise RuntimeError(
				"Order worksheet headers are in an unexpected format; migration aborted to avoid data corruption"
			)

		non_empty_headers = {header for header in canonical_headers if header}
		allowed_headers = set(ORDER_SHEET_COLUMNS)
		unexpected_headers = sorted(non_empty_headers - allowed_headers)
		if unexpected_headers:
			raise RuntimeError(
				f"Order worksheet contains unexpected headers that cannot be mapped safely: {unexpected_headers}"
			)

		logging.info("Order schema migration detected: creating backup and reordering columns")
		backup_title = f"Orders Backup {datetime.now().strftime('%Y-%m-%d %H-%M')}"
		max_cols = max((len(row) for row in rows), default=len(ORDER_SHEET_COLUMNS))
		backup = self.spreadsheet.add_worksheet(
			title=backup_title,
			rows=max(len(rows), 1),
			cols=max(max_cols, len(ORDER_SHEET_COLUMNS)),
		)
		if rows:
			backup.update("A1", rows)
		logging.info("Order schema migration backup created: %s", backup_title)

		header_index_by_name = {
			header: index
			for index, header in enumerate(canonical_headers)
			if header
		}
		reordered_rows = [ORDER_SHEET_COLUMNS]
		for source_row in rows[1:]:
			reordered_rows.append(
				[
					source_row[header_index_by_name[name]]
					if name in header_index_by_name and header_index_by_name[name] < len(source_row)
					else ""
					for name in ORDER_SHEET_COLUMNS
				]
			)

		worksheet.clear()
		worksheet.update("A1", reordered_rows)
		logging.info("Order schema migration completed successfully")

	def _append_order_with_sequential_id(self, row_values: dict[str, Any], created_at: datetime) -> str:
		worksheet = self._get_first_worksheet()
		rows = worksheet.get_all_values()
		counters_worksheet = self._get_or_create_order_counters_worksheet()

		year = created_at.strftime("%Y")
		month = created_at.strftime("%m")
		prefix = f"LT-{self._normalized_bakery_code()}-{year}-{month}-"
		pattern = re.compile(rf"^{re.escape(prefix)}(\d{{3}})$")

		order_id_column_index = ORDER_SHEET_COLUMNS.index(COL_ORDER_ID)
		highest_sequence = 0
		for row in rows[1:]:
			if order_id_column_index >= len(row):
				continue
			order_id = (row[order_id_column_index] or "").strip()
			if not order_id:
				continue

			match = pattern.match(order_id)
			if match is None:
				continue

			sequence = int(match.group(1))
			if sequence > highest_sequence:
				highest_sequence = sequence

		counter_rows = counters_worksheet.get_all_values()
		counter_row_number: int | None = None
		counter_sequence = 0
		for row_number, row in enumerate(counter_rows[1:], start=2):
			stored_prefix = row[0].strip() if len(row) >= 1 else ""
			if stored_prefix != prefix:
				continue

			counter_row_number = row_number
			stored_sequence_text = row[1].strip() if len(row) >= 2 else ""
			if stored_sequence_text.isdigit():
				counter_sequence = int(stored_sequence_text)
			break

		next_sequence = max(counter_sequence, highest_sequence) + 1
		if next_sequence > 999:
			logging.error(
				"Order ID monthly sequence overflow for prefix %s (next=%s). Cannot create a unique ID.",
				prefix,
				next_sequence,
			)
			raise RuntimeError("Order ID sequence overflow for current bakery/month")

		generated_order_id = f"{prefix}{next_sequence:03d}"
		logging.info(
			"Generated sequential order ID %s (prefix=%s)",
			generated_order_id,
			prefix,
		)

		if counter_row_number is None:
			counters_worksheet.append_row([prefix, str(next_sequence)])
		else:
			counters_worksheet.update_cell(counter_row_number, 2, str(next_sequence))

		row_values[COL_ORDER_ID] = generated_order_id

		worksheet.append_row(build_order_row(row_values))
		return generated_order_id

	async def append_order(self, row_data: list) -> None:
		await asyncio.to_thread(self._append_row, row_data)

	async def get_all_rows(self) -> list[list[str]]:
		return await asyncio.to_thread(self._get_all_rows)

	async def update_cell(self, row: int, column: int, value: str) -> None:
		await asyncio.to_thread(self._update_cell, row, column, value)

	async def ensure_order_schema(self) -> None:
		await asyncio.to_thread(self._ensure_order_schema)

	async def setup_sheets(self) -> None:
		await asyncio.to_thread(self._setup_sheets)

	async def append_order_with_sequential_id(self, row_values: dict[str, Any], created_at: datetime) -> str:
		async with self._order_append_lock:
			return await asyncio.to_thread(self._append_order_with_sequential_id, row_values, created_at)

	async def test_connection(self) -> bool:
		try:
			title = await asyncio.to_thread(self._get_first_worksheet_title)
			print(title)
			return True
		except Exception as exc:
			print(f"Google Sheets connection test failed: {exc}")
			return False


sheets_service = GoogleSheetsService()
