import os
import dotenv
from dataclasses import dataclass
from typing import List

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
PEXELS_API_KEY = ensure_env_var("PEXELS_API_KEY")


@dataclass
class Category:
    name: str
    key: str


CATEGORIES: List[Category] = [
    Category(name="POLITIKA", key="politika"),
    Category(name="GOSPODARSTVO", key="gospodarstvo"),
    Category(name="KRIMINAL", key="kriminal"),
    Category(name="ŠPORT", key="sport"),
    Category(name="KULTURA", key="kultura"),
    Category(name="ZDRAVJE", key="zdravje"),
    Category(name="OKOLJE", key="okolje"),
    Category(name="LOKALNO", key="lokalno"),
    Category(name="TEHNOLOGIJA & ZNANOST", key="tehnologija-znanost"),
]
