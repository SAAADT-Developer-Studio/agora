"""Provider-related API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import NewsProvider

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("")
async def get_providers(db: Session = Depends(get_db)):
    """Get all providers."""

    providers = db.query(NewsProvider).all()
    return providers


@router.post("/vote/{provider_id}")
async def vote_provider(provider_id: str, db: Session = Depends(get_db)):
    """Vote for a provider."""
    # TODO: Implement voting logic
    # provider = db.query(NewsProvider).filter(NewsProvider.id == provider_id).first()
    # if not provider:
    #     raise HTTPException(status_code=404, detail="Provider not found")
    # # Implement voting logic here

    raise HTTPException(
        status_code=501,
        detail=f"Vote for provider {provider_id} endpoint not implemented",
    )
