from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///gc_solver.db"
    ANTHROPIC_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-sonnet-4-6"
    GC_USERNAME: str = ""
    GC_PASSWORD: str = ""
    PLAYWRIGHT_HEADLESS: bool = True
    RATE_LIMIT_SECONDS: float = 5.0

    model_config = {"env_file": ".env"}


settings = Settings()
