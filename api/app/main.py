"""Main FastAPI application entry point."""

from fastapi import FastAPI
from mangum import Mangum

from app.config import settings
from app.routers import clusters, providers, feed, people

app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    description=settings.API_DESCRIPTION,
)

app.include_router(clusters.router)
app.include_router(providers.router)
app.include_router(feed.router)
app.include_router(people.router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": settings.API_VERSION}


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Welcome to Vidik API",
        "version": settings.API_VERSION,
        "docs": "/docs",
        "health": "/health",
    }


handler = Mangum(app)


# if __name__ == "__main__":
#     import uvicorn

#     uvicorn.run(
#         "main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG
#     )
