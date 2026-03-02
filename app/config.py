"""
app/config.py: Gestión centralizada de configuraciones y secretos.
"""
import os
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    """
    Define todas las variables de entorno necesarias. 
    Se priorizan las variables reales del sistema sobre el archivo .env.
    """
    # Base de datos 1: índice de Dropbox (dropbox_items)
    database_url: str = Field(
        default="postgresql+asyncpg://user:pass@localhost:5433/dropbox_index",
        alias="DATABASE_URL"
    )
    # Base de datos 2: registro de audios/llamadas (mendoza_box.audios_descargados)
    audios_db_url: str = Field(
        default="postgresql+psycopg2://user:pass@localhost:5432/calls_db",
        alias="AUDIOS_DB_URL"
    )
    token_service_url: str = Field(
        default="https://accesstokendropbox-223080314602.us-central1.run.app",
        alias="TOKEN_SERVICE_URL"
    )
    api_secret_key: str = Field(default="930xY0dJ0pD", alias="API_SECRET_KEY")
    # Configuración de Logs
    log_level: str = "INFO"

    # Otras configuraciones (Ej: Dropbox, Secret Manager)
    # dropbox_token: str = Field(default="...", alias="DROPBOX_TOKEN")

    # Configuración de Pydantic
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        extra="ignore"
    )

@lru_cache()
def get_settings() -> Settings:
    """
    Crea una instancia de Settings y la guarda en caché (Singleton).
    Esto evita leer el archivo .env repetidamente en cada consulta.
    """
    return Settings()