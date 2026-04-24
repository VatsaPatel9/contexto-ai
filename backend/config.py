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
    rag_top_k: int = 8
    rag_score_threshold: float = 0.30
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

    # Email-domain gate on signup. Default keeps the current PSU-only
    # behavior; flipping RESTRICT_EMAIL_DOMAIN=false opens signup to
    # any email. ALLOWED_EMAIL_DOMAIN swaps the permitted domain.
    restrict_email_domain: bool = True
    allowed_email_domain: str = "psu.edu"

    # SMTP for transactional email (verification links, password resets).
    # Recommended: Gmail with an App Password — see README / setup notes.
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""   # defaults to smtp_username if empty
    smtp_from_name: str = "Contexto"

    # Email verification: when True, new signups must click a link in
    # the verification email before their session is considered valid.
    # Requires the SMTP_* vars above to be set, otherwise emails won't
    # send and users will be locked out. Flip to False in dev/test.
    email_verification_required: bool = True

    # Cloudflare R2 object storage
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""

    class Config:
        env_file = str(BACKEND_DIR / ".env")
        extra = "ignore"
