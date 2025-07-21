"""Cluster-related API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Cluster

router = APIRouter(prefix="/cluster", tags=["clusters"])


@router.get("/{cluster_id}")
async def get_cluster(cluster_id: str, db: Session = Depends(get_db)):
    """Get cluster by ID."""
    # TODO: Implement cluster retrieval logic
    # cluster = db.query(Cluster).filter(Cluster.id == cluster_id).first()
    # if not cluster:
    #     raise HTTPException(status_code=404, detail="Cluster not found")
    # return cluster

    raise HTTPException(
        status_code=501, detail=f"Cluster {cluster_id} endpoint not implemented"
    )
