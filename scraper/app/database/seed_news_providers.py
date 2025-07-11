from app.providers.providers import PROVIDERS
from app.database.database import Database, NewsProvider, Session
import app.providers.news_provider as news_provider


def seed_new_providers() -> None:
    session = Session()
    # Get existing provider keys from the database
    existing_provider_keys: set[str] = set(
        key for (key,) in session.query(NewsProvider.key).all()
    )

    # Separate providers into new and existing based on keys
    new_providers_data: list[news_provider.NewsProvider] = [
        p for p in PROVIDERS if p.key not in existing_provider_keys
    ]
    existing_providers_data: list[news_provider.NewsProvider] = [
        p for p in PROVIDERS if p.key in existing_provider_keys
    ]

    # Prepare NewsProvider objects for new providers
    new_news_providers: list[NewsProvider] = [
        NewsProvider(name=p.name, key=p.key, url=p.url) for p in new_providers_data
    ]

    # Fetch existing NewsProvider objects that need updates
    existing_news_providers_to_update: list[NewsProvider] = (
        session.query(NewsProvider)
        .filter(NewsProvider.key.in_([p.key for p in existing_providers_data]))
        .all()
    )

    # Create a dictionary for efficient lookup
    existing_news_provider_map = {
        str(p.key): p for p in existing_news_providers_to_update
    }

    # Update attributes of existing NewsProvider objects
    for provider_data in existing_providers_data:
        if provider := existing_news_provider_map.get(provider_data.key):
            provider.name = provider_data.name
            provider.url = provider_data.url

    # Add new providers to the session
    session.add_all(new_news_providers)

    # Existing providers are already managed by the session, changes will be flushed

    # Commit all changes (inserts and updates)
    session.commit()
