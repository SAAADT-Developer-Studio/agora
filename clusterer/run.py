from datetime import datetime, timedelta, timezone
import logging

from database.schema import Story, StoryArticle, StorySummary
from database.unit_of_work import UnitOfWork, database_session

from .assign import LLM, SEED, NeighborIndex, decide
from .judge import same_happening
from .summary import (
    MODEL,
    PROMPT_VERSION,
    ArticleExcerpt,
    Brief,
    bullets_from_json,
    bullets_to_json,
    lead_article,
    refresh_brief,
)

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
    story_ids = {row.story_id for row in assigned}
    stories = uow.stories.get_by_ids(list(story_ids))
    for row in assigned:
        index.add(
            row.article_id,
            row.story_id,
            row.embedding,
            title=row.title,
            summary=row.summary,
            published_at=row.published_at,
            is_seed=row.method == SEED,
        )

    if not unassigned:
        logger.info("No unassigned articles in the %d-day window", WINDOW_DAYS)
        return

    seeded = 0
    cosine = 0
    llm = 0
    for article in unassigned:
        assignment = decide(
            article.embedding,
            index,
            title=article.title,
            summary=article.summary,
            judge=same_happening,
        )
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
            index.add(
                article.id,
                story.id,
                article.embedding,
                title=article.title,
                summary=article.summary,
                published_at=article.published_at,
                is_seed=True,
            )
            _refresh_summary(uow, story)
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
        index.add(
            article.id,
            story.id,
            article.embedding,
            title=article.title,
            summary=article.summary,
            published_at=article.published_at,
            is_seed=False,
        )
        _refresh_summary(uow, story)
        if assignment.method == LLM:
            llm += 1
        else:
            cosine += 1

    logger.info(
        "Assigned %d articles (%d seeded, %d cosine, %d llm)",
        seeded + cosine + llm,
        seeded,
        cosine,
        llm,
    )


def _refresh_summary(uow: UnitOfWork, story: Story) -> None:
    uow.session.flush()
    excerpts = [
        ArticleExcerpt(
            article_id=row.article_id,
            title=row.title,
            deck=row.deck,
            summary=row.summary,
            published_at=row.published_at,
        )
        for row in uow.stories.member_texts(story.id)
    ]
    stored = uow.stories.latest_summary(story.id)
    previous = (
        Brief(
            title=stored.title,
            bullets=bullets_from_json(stored.bullets),
            lead_article_id=stored.lead_article_id,
        )
        if stored is not None
        else None
    )
    brief = refresh_brief(excerpts, previous)
    if brief is None:
        lead = lead_article(excerpts)
        if previous is None and lead is not None:
            story.title = lead.title
        return
    uow.stories.add_summary(
        StorySummary(
            story_id=story.id,
            title=brief.title,
            bullets=bullets_to_json(brief.bullets),
            lead_article_id=brief.lead_article_id,
            model=MODEL,
            prompt_version=PROMPT_VERSION,
        )
    )
    story.title = brief.title
    logger.info("Story %s summary: %s (%d bullets)", story.id, brief.title, len(brief.bullets))
