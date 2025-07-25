# Vidik API

REST API for the Vidik news aggregation platform.

## Project Structure

```
api/
├── app/
│   ├── __init__.py
│   ├── main.py                # FastAPI application entry point
│   ├── config.py              # Configuration settings
│   ├── database/
│   │   └── __init__.py        # Database connection and session management
│   ├── models/
│   │   └── __init__.py        # Database models (reflected from scraper schema)
│   └── routers/
│       ├── __init__.py
│       ├── clusters.py        # Cluster endpoints
│       ├── feed.py           # Feed endpoints
│       ├── people.py         # People mentioned endpoints
│       └── providers.py      # Provider endpoints
├── main.py                   # FastAPI application entry point
├── .env.example             # Environment variables template
├── pyproject.toml           # Project dependencies
└── README.md
```

## Setup

1. Copy environment file:

```bash
cp .env.example .env
```

2. Update `.env` with your database configuration

3. Install dependencies:

```bash
uv sync
```

4. Run the API:

```bash
# uv run python main.py
uv run fastapi dev
```

## API Endpoints

- `GET /cluster/{cluster_id}` - Get cluster by ID
- `GET /providers` - Get all providers
- `GET /feed` - Get general feed
- `GET /feed/{category}` - Get feed by category
- `GET /people-mentioned/{category}` - Get people mentioned in category
- `POST /vote/{provider_id}` - Vote for a provider
- `GET /health` - Health check
- `GET /` - API information

## Development

The API documentation is available at `/docs` when running the server.

All endpoints are currently placeholders returning 501 status codes with TODO comments for implementation.

All endpoints currently return placeholder responses with 501 status codes (Not Implemented).

## Development

The API automatically serves documentation at:

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
