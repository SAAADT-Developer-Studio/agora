from datetime import datetime, timedelta, timezone
import logging

from database.schema import Story, StoryArticle, StorySummary
from database.unit_of_work import UnitOfWork, database_session

from .assign import Assignment
from .pipeline import WINDOW_DAYS, MergeMemory, Models, NewArticle, load_index, run_batch
from .summary import (
    MODEL,
    PROMPT_VERSION,
    ArticleExcerpt,
    Brief,
    bullets_from_json,
    bullets_to_json,
)

logger = logging.getLogger(__name__)
# Lives as long as the scheduler process, so a rejected merge is not re-asked every run.
_merge_memory = MergeMemory()


def run() -> None:
    logger.info("clusterer running")
    with database_session() as uow:
        _assign_unassigned(uow)


def _assign_unassigned(uow: UnitOfWork) -> None:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=WINDOW_DAYS)
    assigned = uow.stories.get_assigned_since(since)
    unassigned = uow.stories.get_unassigned_since(since)
    if not unassigned:
        logger.info("No unassigned articles in the %d-day window", WINDOW_DAYS)
        return

    story_ids = list({row.story_id for row in assigned})
    store = DatabaseStore(uow, uow.stories.get_by_ids(story_ids))
    briefs = {
        story_id: _brief(stored)
        for story_id, stored in uow.stories.latest_summaries(story_ids).items()
    }
    index = load_index(assigned, briefs, uow.stories.first_published(story_ids))
    stats = run_batch(
        index, unassigned, store, Models.production(), now=now, memory=_merge_memory
    )
    logger.info(
        "Assigned %d articles (%d seeded, %d cosine, %d llm), merged %d stories",
        stats.seeded + stats.cosine + stats.llm,
        stats.seeded,
        stats.cosine,
        stats.llm,
        stats.merged,
    )


class DatabaseStore:
    def __init__(self, uow: UnitOfWork, stories: dict[int, Story]) -> None:
        self._uow = uow
        self._stories = stories

    def create_story(self, article: NewArticle) -> int:
        story = Story(title=article.title, last_article_published_at=article.published_at)
        self._uow.stories.create(story)
        self._uow.session.flush()
        self._stories[story.id] = story
        return story.id

    def add_membership(self, story_id: int, article: NewArticle, assignment: Assignment) -> None:
        story = self._stories[story_id]
        if article.published_at > story.last_article_published_at:
            story.last_article_published_at = article.published_at
        self._uow.stories.add_membership(
            StoryArticle(
                story_id=story_id,
                article_id=article.id,
                method=assignment.method,
                similarity=assignment.similarity,
                story_similarity=assignment.story_similarity,
                nearest_article_id=assignment.nearest_article_id,
                judge_relation=assignment.relation,
            )
        )

    def merge(self, drop_id: int, keep_id: int) -> None:
        self._uow.stories.merge(self._stories[drop_id], self._stories[keep_id])

    def excerpts(self, story_id: int) -> list[ArticleExcerpt]:
        self._uow.session.flush()
        return [
            ArticleExcerpt(
                article_id=row.article_id,
                title=row.title,
                deck=row.deck,
                summary=row.summary,
                published_at=row.published_at,
            )
            for row in self._uow.stories.member_texts(story_id)
        ]

    def latest_brief(self, story_id: int) -> Brief | None:
        stored = self._uow.stories.latest_summary(story_id)
        return _brief(stored) if stored is not None else None

    def save_brief(self, story_id: int, brief: Brief) -> None:
        self._uow.stories.add_summary(
            StorySummary(
                story_id=story_id,
                title=brief.title,
                bullets=bullets_to_json(brief.bullets),
                lead_article_id=brief.lead_article_id,
                lede=brief.lede,
                model=MODEL,
                prompt_version=PROMPT_VERSION,
            )
        )
        self._stories[story_id].title = brief.title

    def set_title(self, story_id: int, title: str) -> None:
        self._stories[story_id].title = title


def _brief(stored: StorySummary) -> Brief:
    return Brief(
        title=stored.title,
        bullets=bullets_from_json(stored.bullets),
        lead_article_id=stored.lead_article_id,
        created_at=stored.created_at,
        lede=stored.lede,
    )
