"""Load the stories an observation ranking run scores.

The feed does not read the result. This module only selects stories. It does
not update story, story_article, or any cluster table.
"""

from datetime import datetime
from typing import Sequence

from sqlalchemy import exists, select
from sqlalchemy.orm import load_only, selectinload

from database.schema import Article, NewsProvider, Story, StoryArticle


def story_ranking_statement(*, since: datetime, after_id: int, limit: int):
    """One page of stories whose latest article is inside the observation window.

    Scope matches the stories /novo keeps in view, plus the rows ranking can
    actually score:

    - ``last_article_published_at >= since`` (the caller passes 14 days).
      The predicate leads with that column so PostgreSQL can range-scan
      ``ix_story_last_article_published_at``. The story path does not read
      ``cluster_v2`` and does not use the cluster expiry index.
    - ``merged_into_story_id IS NULL``. Merged stories are redirects.
    - at least one ``story_article`` row. An empty story has nothing to score.

    Pages advance by story id. Ids are stable, so a committed page is not
    loaded again and a failed page retries only its own rows.
    """
    if limit < 1:
        raise ValueError("limit must be positive")
    return (
        select(Story)
        .where(
            Story.last_article_published_at >= since,
            Story.merged_into_story_id.is_(None),
            Story.id > after_id,
            exists(select(StoryArticle.id).where(StoryArticle.story_id == Story.id)),
        )
        .order_by(Story.id)
        .limit(limit)
        .options(
            load_only(Story.id, Story.last_article_published_at, Story.merged_into_story_id),
            selectinload(Story.memberships)
            .selectinload(StoryArticle.article)
            .load_only(
                Article.id, Article.title, Article.published_at, Article.first_seen_at,
                Article.summary, Article.content, Article.categories, Article.llm_rank,
                Article.embedding, Article.news_provider_key,
            )
            .selectinload(Article.news_provider)
            .load_only(NewsProvider.key, NewsProvider.rank),
        )
    )


def load_story_batch(
    session, *, since: datetime, after_id: int = 0, limit: int = 100,
) -> Sequence[Story]:
    """Load one page with each member's article history already populated."""
    return session.scalars(
        story_ranking_statement(since=since, after_id=after_id, limit=limit)
    ).all()
