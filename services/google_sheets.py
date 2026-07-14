import asyncio
from pathlib import Path

import gspread

from config.config import settings


BASE_DIR = Path(__file__).resolve().parent.parent


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

	def _get_first_worksheet_title(self) -> str:
		worksheet = self.spreadsheet.get_worksheet(0)
		if worksheet is None:
			raise RuntimeError("The spreadsheet does not contain any worksheets")
		return worksheet.title

	def _append_row(self, row_data: list) -> None:
		worksheet = self.spreadsheet.get_worksheet(0)
		if worksheet is None:
			raise RuntimeError("The spreadsheet does not contain any worksheets")
		worksheet.append_row(row_data)

	async def append_order(self, row_data: list) -> None:
		await asyncio.to_thread(self._append_row, row_data)

	async def test_connection(self) -> bool:
		try:
			title = await asyncio.to_thread(self._get_first_worksheet_title)
			print(title)
			return True
		except Exception as exc:
			print(f"Google Sheets connection test failed: {exc}")
			return False


sheets_service = GoogleSheetsService()
