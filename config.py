from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    """Application configuration settings."""
    
    # OpenAI API Configuration
    openai_api_key: str = "sk-dummy-key-replace-with-real-key"
    
    # Whisper model to use (e.g. tiny, base, small, medium, large-v2, large-v3)
    whisper_model: str = "large-v2"
    
    # Hugging Face Configuration for Diarization
    huggingface_token: str = "hf-dummy-token-replace-with-real-token"
    deepgram_api_key: str = "YOUR_KEY"

    
    # Diarization model configuration
    diarization_model: str = "pyannote/speaker-diarization-3.1"
    
    # Output folder configuration
    output_folder: Path = Path("output")
    
    # File upload constraints
    max_file_size_mb: int = 25  # OpenAI limit is 25MB
    allowed_extensions: list[str] = [".wav", ".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".webm"]
    
    # LLM Formatting Configuration
    enable_llm_formatting: bool = True
    llm_model: str = "gpt-4o-mini"  # Cost-efficient model for formatting
    formatting_style: str = "professional"  # Options: professional, meeting, interview, subtitle
    
    # Database Configuration
    db_server: str = "161.97.142.50"
    db_name: str = "TranscriptionAI"
    db_user: str = "ra"
    db_password: str = "ramp@123"
    db_driver: str = "ODBC Driver 17 for SQL Server"
    db_trusted_connection: str = "yes"
    
    @property
    def database_url(self) -> str:
        """Construct SQLAlchemy database URL for SQL Server."""
        if self.db_trusted_connection.lower() == "yes":
            # Windows Authentication
            params = f"?driver={self.db_driver}&trusted_connection=yes"
            return f"mssql+pyodbc://@{self.db_server}/{self.db_name}{params}"
        else:
            # SQL Authentication
            params = f"?driver={self.db_driver}"
            return f"mssql+pyodbc://{self.db_user}:{self.db_password}@{self.db_server}/{self.db_name}{params}"

    # API Timeout Configuration (in seconds)
    openai_timeout: int = 600  # 10 minutes for long audio files
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Global settings instance
settings = Settings()
