from pathlib import Path

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
	model_config = SettingsConfigDict(
		env_file=BASE_DIR / ".env",
		env_file_encoding="utf-8",
		extra="ignore",
	)

	bot_token: SecretStr = Field(validation_alias="BOT_TOKEN")
	spreadsheet_id: str = Field(validation_alias="SPREADSHEET_ID")
	bakery_code: str = Field(default="LMS", validation_alias="BAKERY_CODE")
	bakery_phone: str = Field(default="", validation_alias="BAKERY_PHONE")


try:
	settings = Settings()
except ValidationError as exc:
	missing_fields = ", ".join(
		error["loc"][0]
		for error in exc.errors()
		if error.get("type") == "missing" and error.get("loc")
	)
	if missing_fields:
		raise RuntimeError(
			f"Missing required environment variables: {missing_fields}"
		) from exc
	raise RuntimeError(f"Failed to load settings: {exc}") from exc
