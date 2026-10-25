"""Load the stories an observation ranking run scores.

The feed does not read the result. This module only selects stories. It does
not update story, story_article, or any cluster table.
"""

from datetime import datetime
from typing import Sequence

from sqlalchemy import exists, select
from sqlalchemy.orm import load_only, selectinload

from database.schema import Article, NewsProvider, Story, StoryArticle, StoryRank


def story_ranking_statement(
    *, since: datetime, after_id: int = 0, limit: int, ranking_run_id: int | None = None,
):
    """One page of stories whose latest article is inside the observation window.

    Scope matches the stories /novo keeps in view, plus the rows ranking can
    actually score:

    - ``last_article_published_at >= since`` (the caller passes 14 days).
      That column is not the page cursor. The clusterer updates it on the
      same clock as this job, and a cursor on it selects a story again after
      the timestamp moves forward.
    - pages advance by ``story.id``. Ids do not move, so a committed page is
      not loaded again. The plan is a ``story_pkey`` walk with the time
      predicate as a filter.
    - ``merged_into_story_id IS NULL``. Merged stories are redirects.
    - at least one ``story_article`` row. An empty story has nothing to score.
    - when ``ranking_run_id`` is set, stories that already have a ``story_rank``
      for that run are left out.

    The story path does not read ``cluster_v2`` and does not use the cluster
    expiry index.
    """
    if limit < 1:
        raise ValueError("limit must be positive")
    filters = [
        Story.last_article_published_at >= since,
        Story.merged_into_story_id.is_(None),
        Story.id > after_id,
        exists(select(StoryArticle.id).where(StoryArticle.story_id == Story.id)),
    ]
    if ranking_run_id is not None:
        filters.append(~exists(
            select(StoryRank.story_id).where(
                StoryRank.ranking_run_id == ranking_run_id,
                StoryRank.story_id == Story.id,
            )
        ))
    return (
        select(Story)
        .where(*filters)
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
    ranking_run_id: int | None = None,
) -> Sequence[Story]:
    """Load one page with each member's article history already populated."""
    return session.scalars(
        story_ranking_statement(
            since=since, after_id=after_id, limit=limit, ranking_run_id=ranking_run_id,
        )
    ).all()
