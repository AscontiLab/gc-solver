from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///gc_solver.db"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"
    GC_USERNAME: str = ""
    GC_PASSWORD: str = ""
    PLAYWRIGHT_HEADLESS: bool = True
    RATE_LIMIT_SECONDS: float = 5.0
    ADMIN_TOKEN: str = ""

    model_config = {"env_file": ".env"}


settings = Settings()
