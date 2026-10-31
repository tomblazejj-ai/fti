from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchored to the backend folder so the DB and .env are the same no matter
# which directory the server is started from.
BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    fred_api_key: str = ""  # optional — FRED works keyless via its public CSV download
    bls_api_key: str = ""
    bea_api_key: str = ""
    eia_api_key: str = ""
    cftc_app_token: str = ""
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'fti.db').as_posix()}"


settings = Settings()
