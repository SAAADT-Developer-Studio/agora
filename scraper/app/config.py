import os
import dotenv
from dataclasses import dataclass
from typing import List, TypedDict

from app.utils.ensure_env_var import ensure_env_var

dotenv.load_dotenv()


class TimeDict(TypedDict, total=False):
    days: float
    seconds: float
    microseconds: float
    milliseconds: float
    minutes: float
    hours: float
    weeks: float


# Default time window for fetching recent articles, can be overridden by individual providers
TIME_WINDOW: TimeDict = {
    "minutes": 30,
}

APP_ENV = ensure_env_var("APP_ENV")
GOOGLE_API_KEY = ensure_env_var("GOOGLE_API_KEY")
OPENAI_API_KEY = ensure_env_var("OPENAI_API_KEY")
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
