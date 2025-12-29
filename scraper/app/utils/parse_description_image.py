from bs4 import BeautifulSoup, Tag


def parse_description_image(description: str) -> str | None:
    """Parse the first image URL from the HTML description."""

    soup = BeautifulSoup(description, "html.parser")
    img_tag = soup.find("img")
    if isinstance(img_tag, Tag):
        src = img_tag.get("src")
        if isinstance(src, str):
            return src
    return None
