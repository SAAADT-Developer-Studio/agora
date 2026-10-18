from datetime import datetime, timedelta, timezone
import logging

from database.schema import Story, StoryArticle, StorySummary
from database.unit_of_work import UnitOfWork, database_session

from .assign import LLM, SEED, NeighborIndex, decide
from .judge import same_happening, same_story
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
    story_ids = list({row.story_id for row in assigned})
    stories = uow.stories.get_by_ids(story_ids)
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
    for story_id, stored in uow.stories.latest_summaries(story_ids).items():
        index.set_brief(
            story_id, stored.title, [bullet.text for bullet in bullets_from_json(stored.bullets)]
        )

    if not unassigned:
        logger.info("No unassigned articles in the %d-day window", WINDOW_DAYS)
        return

    changed: set[int] = set()
    seeded = 0
    cosine = 0
    llm = 0
    for article in unassigned:
        assignment = decide(
            article.embedding,
            index,
            title=article.title,
            summary=article.summary,
            published_at=article.published_at,
            judge=same_happening,
        )
        if assignment.story_id is None:
            story = Story(
                title=article.title,
                last_article_published_at=article.published_at,
            )
            uow.stories.create(story)
            uow.session.flush()
            stories[story.id] = story
            seeded += 1
        else:
            story = stories[assignment.story_id]
            if article.published_at > story.last_article_published_at:
                story.last_article_published_at = article.published_at
            if assignment.method == LLM:
                llm += 1
            else:
                cosine += 1
        uow.stories.add_membership(
            StoryArticle(
                story_id=story.id,
                article_id=article.id,
                method=assignment.method,
                similarity=assignment.similarity,
                story_similarity=assignment.story_similarity,
                nearest_article_id=assignment.nearest_article_id,
            )
        )
        index.add(
            article.id,
            story.id,
            article.embedding,
            title=article.title,
            summary=article.summary,
            published_at=article.published_at,
            is_seed=assignment.story_id is None,
        )
        changed.add(story.id)
        _refresh_summary(uow, story, index)

    logger.info(
        "Assigned %d articles (%d seeded, %d cosine, %d llm)",
        seeded + cosine + llm,
        seeded,
        cosine,
        llm,
    )
    _merge_duplicates(uow, index, stories, changed)


def _merge_duplicates(
    uow: UnitOfWork, index: NeighborIndex, stories: dict[int, Story], changed: set[int]
) -> None:
    """Merge stories that cover the same event, e.g. after two seeds grew side by side.

    Only pairs touched this run are judged, so a rejected pair is not asked
    again every run unless one of the stories grows.
    """
    merged: set[int] = set()
    for pair in index.merge_candidates(changed):
        if pair.keep_story_id in merged or pair.drop_story_id in merged:
            continue
        try:
            same = same_story(
                index.story_context(pair.keep_story_id), index.story_context(pair.drop_story_id)
            )
        except Exception:
            logger.warning("Story merge judge failed", exc_info=True)
            continue
        if not same:
            continue
        keep = stories[pair.keep_story_id]
        drop = stories[pair.drop_story_id]
        uow.stories.merge(drop, keep)
        index.move(drop.id, keep.id)
        merged.add(drop.id)
        logger.info(
            "Merged story %s into %s (centroid cosine %.3f)", drop.id, keep.id, pair.similarity
        )
        _refresh_summary(uow, keep, index, force=True)


def _refresh_summary(
    uow: UnitOfWork, story: Story, index: NeighborIndex, *, force: bool = False
) -> None:
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
    brief = refresh_brief(excerpts, previous, force=force)
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
    index.set_brief(story.id, brief.title, [bullet.text for bullet in brief.bullets])
    logger.info("Story %s summary: %s (%d bullets)", story.id, brief.title, len(brief.bullets))
