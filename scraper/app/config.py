import os
import dotenv

dotenv.load_dotenv()


def ensure_env_var(var_name: str) -> str:
    """
    Ensure that the environment variable is set.
    Raises ValueError if the variable is not set.
    """
    value = os.getenv(var_name)
    if not value:
        raise ValueError(f"'{var_name}' environment variable is not set.")
    return value


TIME_WINDOW = {
    "minutes": 20,
}

APP_ENV = ensure_env_var("APP_ENV")
GOOGLE_API_KEY = ensure_env_var("GOOGLE_API_KEY")
DATABASE_URL = ensure_env_var("DATABASE_URL")
