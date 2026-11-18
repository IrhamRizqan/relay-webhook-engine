from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME:str = "Relay Webhook Engine"
    DATABASE_URL:str = "postgresql+asyncpg://relay_user:relay_password@localhost:5433/relay_db"
    REDIS_HOST:str = "localhost"
    REDIS_PORT:int = "6381"
    MAX_RETRY_ATTEMPTS:int = 4

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()