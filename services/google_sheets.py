import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import gspread
from gspread.exceptions import WorksheetNotFound

from config.config import settings
from services.order_sheet_schema import COL_ORDER_ID, ORDER_SHEET_COLUMNS, build_order_row


BASE_DIR = Path(__file__).resolve().parent.parent
ORDER_COUNTERS_WORKSHEET_TITLE = "Order Counters"
ORDER_COUNTERS_HEADERS = ["Prefix", "Last sequence"]


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

	def _get_first_worksheet(self):
		worksheet = self.spreadsheet.get_worksheet(0)
		if worksheet is None:
			raise RuntimeError("The spreadsheet does not contain any worksheets")
		return worksheet

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
		headers = worksheet.row_values(1)
		cells_to_update: list[tuple[int, str]] = []

		for column, expected_header in enumerate(ORDER_SHEET_COLUMNS, start=1):
			current_header = headers[column - 1].strip() if column <= len(headers) else ""
			if column >= 9 and current_header and current_header != expected_header:
				raise RuntimeError(
					f"Managed header mismatch at column {column}: expected '{expected_header}', found '{current_header}'"
				)
			if current_header:
				continue
			cells_to_update.append((column, expected_header))

		for column, expected_header in cells_to_update:
			worksheet.update_cell(1, column, expected_header)

		self._get_or_create_order_counters_worksheet()

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
