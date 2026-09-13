from datetime import datetime, timedelta, timezone
import logging

from database.schema import Story, StoryArticle
from database.unit_of_work import UnitOfWork, database_session

from .assign import NeighborIndex, decide

WINDOW_DAYS = 3

logger = logging.getLogger(__name__)


def run() -> None:
    logger.info("clusterer running")
    with database_session() as uow:
        _assign_unassigned(uow)


def _assign_unassigned(uow: UnitOfWork) -> None:
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    assigned = uow.stories.get_assigned_since(since)
    unassigned = uow.stories.get_unassigned_since(since)

    index = NeighborIndex()
    story_ids = {story_id for _, story_id, _ in assigned}
    stories = uow.stories.get_by_ids(list(story_ids))
    for article_id, story_id, embedding in assigned:
        index.add(article_id, story_id, embedding)

    if not unassigned:
        logger.info("No unassigned articles in the %d-day window", WINDOW_DAYS)
        return

    seeded = 0
    joined = 0
    for article in unassigned:
        assignment = decide(article.embedding, index)
        if assignment.story_id is None:
            story = Story(
                title=article.title,
                last_article_published_at=article.published_at,
            )
            uow.stories.create(story)
            uow.session.flush()
            uow.stories.add_membership(
                StoryArticle(
                    story_id=story.id,
                    article_id=article.id,
                    method=assignment.method,
                    similarity=assignment.similarity,
                    nearest_article_id=assignment.nearest_article_id,
                )
            )
            stories[story.id] = story
            index.add(article.id, story.id, article.embedding)
            seeded += 1
            continue

        story = stories[assignment.story_id]
        uow.stories.add_membership(
            StoryArticle(
                story_id=story.id,
                article_id=article.id,
                method=assignment.method,
                similarity=assignment.similarity,
                nearest_article_id=assignment.nearest_article_id,
            )
        )
        if article.published_at > story.last_article_published_at:
            story.last_article_published_at = article.published_at
        index.add(article.id, story.id, article.embedding)
        joined += 1

    logger.info("Assigned %d articles (%d seeded, %d joined)", seeded + joined, seeded, joined)
