"""People mentioned API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db

router = APIRouter(prefix="/people-mentioned", tags=["people"])


@router.get("/{category}")
async def get_people_mentioned(category: str, db: Session = Depends(get_db)):
    """Get people mentioned in category."""
    # TODO: Implement people mentioned retrieval logic
    # This would require NLP analysis of articles to extract mentioned people
    # people = db.query(...).filter_by(category=category).all()
    # return people

    raise HTTPException(
        status_code=501,
        detail=f"People mentioned in category {category} endpoint not implemented",
    )
