import re
import unicodedata


def slugify(text: str) -> str:
    # Normalize text to remove accents
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    # Replace non-alphanumeric characters with hyphens
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text)
    # Remove leading/trailing hyphens and lowercase it
    return text.strip("-").lower()
