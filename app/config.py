from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    openai_transcription_model: str = "gpt-transcribe"
    openai_analysis_model: str = ""
    openai_use_files_api: bool = False
    openai_fake: bool = False  # somente testes/desenvolvimento: respostas simuladas, sem chamadas externas

    max_audio_upload_mb: int = 24
    max_recording_minutes: int = 90
    max_attachment_mb: int = 20
    max_attachments_per_attendance: int = 15
    temp_audio_ttl_hours: int = 72
    max_ai_calls_per_user_per_day: int = 200

    database_url: str = "sqlite:///./data/atendimento.db"
    storage_dir: str = "./storage"
    storage_audio_dir: str = "./storage_audio_tmp"  # áudio temporário: diretório separado, fora das rotinas de backup
    storage_encryption_key: str = ""
    session_cookie_secure: bool = True
    session_hours: int = 12
    run_worker_in_process: bool = True
    worker_poll_seconds: float = 2.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
