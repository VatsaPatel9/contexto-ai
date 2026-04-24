from pathlib import Path

from pydantic_settings import BaseSettings

BACKEND_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    database_url: str = "postgresql://tutor_dev@localhost:5432/tutor_dev"
    openai_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    rag_chunk_size: int = 1000
    rag_chunk_overlap: int = 200
    rag_top_k: int = 5
    rag_score_threshold: float = 0.45
    course_name: str = "the uploaded course materials"
    enable_humanizer: bool = False
    cors_allow_origins: str = "*"

    # Vision extraction
    vision_model: str = "gpt-5.4-nano"
    enable_vision_extraction: bool = True

    # SuperTokens
    supertokens_connection_uri: str = "http://localhost:3567"
    supertokens_api_key: str = ""
    auth_api_domain: str = "http://localhost"
    auth_website_domain: str = "http://localhost"

    # Cloudflare R2 object storage
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""

    class Config:
        env_file = str(BACKEND_DIR / ".env")
        extra = "ignore"
