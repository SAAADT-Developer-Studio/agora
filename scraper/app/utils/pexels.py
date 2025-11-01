import httpx
import logging
from app import config


async def search_pexels_image(query: str) -> str | None:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.pexels.com/v1/search",
                params={"query": query, "orientation": "landscape", "per_page": 1},
                headers={"Authorization": config.PEXELS_API_KEY},
                timeout=5.0,
            )
            response.raise_for_status()

            data = response.json()
            photos = data.get("photos", [])

            if photos:
                return photos[0]["src"]["large"]
            return None
    except Exception as e:
        logging.error(f"Error searching Pexels for '{query}': {e}")
        return None
