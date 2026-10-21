from pathlib import Path

from pydantic import computed_field
from pydantic_core import MultiHostUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent  # <project>/backend/src
ENV_FILE_PATH = BASE_DIR.parent.parent / '.env'  # <project>/.env


class Settings(BaseSettings):
    """Настройки приложения, загружаемые из переменных окружения и .env файла."""

    model_config = SettingsConfigDict(env_file=str(ENV_FILE_PATH), extra='ignore')

    # --- API ---
    API_PREFIX: str = '/api/v1'
    API_VERSION: str = '0.1.0'
    API_TITLE: str = 'TokenGen API'
    API_DESCRIPTION: str = 'Token Generation Service'

    # --- Postgres ---
    POSTGRES_HOST: str
    POSTGRES_PORT: int
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str

    # --- Provider ---
    PROVIDER_TIMEOUT: int = 60
    PROVIDER_ALPHA_URL: str
    PROVIDER_BETA_URL: str
    PROVIDER_SHARED_SECRET: str

    # --- Webhook ---
    WEBHOOK_BASE_URL: str

    # --- Logging ---
    LOG_LEVEL: str = 'INFO'

    def build_database_url(self, scheme: str) -> str:
        return str(
            MultiHostUrl.build(
                scheme=scheme,
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=self.POSTGRES_HOST,
                port=self.POSTGRES_PORT,
                path=self.POSTGRES_DB,
            ),
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DB_URL(self) -> str:  # noqa: N802
        return self.build_database_url('postgresql+asyncpg')

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_SYNC_DB_URL(self) -> str:  # noqa: N802
        return self.build_database_url('postgresql+psycopg2')


settings = Settings()
