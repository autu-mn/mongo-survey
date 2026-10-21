from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    mongo_uri: str = "mongodb://127.0.0.1:27017"
    mongo_db: str = "survey_system"
    jwt_secret: str = "change-me-in-production"
    jwt_expire_minutes: int = 60 * 24
    bcrypt_rounds: int = 12


settings = Settings()
