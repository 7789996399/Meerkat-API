"""
Meerkat Governance API -- Application entry point.

Run with:
    uvicorn api.main:app --reload

Then open http://localhost:8000 for the login page,
or http://localhost:8000/docs for the interactive Swagger UI.

This file:
  1. Creates the FastAPI application
  2. Adds CORS middleware (permissive for demo, locked down in production)
  3. Mounts all route modules (verify, shield, audit, configure, dashboard)
  4. Serves the frontend (login page, dashboard app)
  5. Defines the health check endpoint
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse

from api.routes import audit, configure, dashboard, shield, verify

# ---------------------------------------------------------------------------
# Create the FastAPI application
#
# The metadata here powers the auto-generated Swagger docs at /docs.
# title, version, and description all show up in the UI header.
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Meerkat Governance API",
    version="0.1.0-alpha",
    description=(
        "AI Governance as a Service. "
        "Meerkat sits between AI models and end users, verifying every response "
        "for hallucinations, bias, prompt attacks, and compliance violations.\n\n"
        "**One API. Any AI model. Every regulated industry.**\n\n"
        "---\n\n"
        "## Core Endpoints\n\n"
        "| Endpoint | Purpose |\n"
        "|----------|--------|\n"
        "| `POST /v1/verify` | Verify an AI response (trust score + governance checks) |\n"
        "| `POST /v1/shield` | Scan user input for prompt injection attacks |\n"
        "| `GET /v1/audit/{id}` | Retrieve a compliance audit record |\n"
        "| `POST /v1/configure` | Set org-specific governance rules |\n"
        "| `GET /v1/dashboard` | Get aggregated governance metrics |\n\n"
        "---\n\n"
        "**Status:** Alpha (demo mode -- simulated governance scores).\n\n"
        "Built by Jean & CL -- Vancouver, BC."
    ),
)

# ---------------------------------------------------------------------------
# CORS Middleware
#
# Cross-Origin Resource Sharing: controls which websites can call our API.
# For the demo, we allow everything ("*"). In production, you'd restrict
# this to your frontend domain(s) only.
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],         # Allow any origin (demo only)
    allow_credentials=True,
    allow_methods=["*"],         # Allow all HTTP methods
    allow_headers=["*"],         # Allow all headers
)

# ---------------------------------------------------------------------------
# Mount route modules
#
# Each router handles one group of endpoints. This keeps the code organized:
# one file per resource instead of everything in main.py.
# ---------------------------------------------------------------------------

app.include_router(verify.router)
app.include_router(shield.router)
app.include_router(audit.router)
app.include_router(configure.router)
app.include_router(dashboard.router)


# ---------------------------------------------------------------------------
# Frontend routes
#
# Resolve the frontend directory relative to this file so it works both
# when running locally (uvicorn api.main:app) and inside Docker.
# ---------------------------------------------------------------------------

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@app.get("/", include_in_schema=False)
async def root():
    """Redirect root to the login page."""
    return RedirectResponse(url="/login")


@app.get("/login", include_in_schema=False)
async def login_page():
    """Serve the MEERKAT login page."""
    return FileResponse(FRONTEND_DIR / "login.html")


@app.get("/app", include_in_schema=False)
async def dashboard_page():
    """Serve the governance dashboard (React app)."""
    return FileResponse(FRONTEND_DIR / "dashboard.html")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get(
    "/v1/health",
    summary="Health check",
    description="Returns the current status of the API. Use this for uptime monitoring.",
    tags=["System"],
)
async def health():
    """Simple health check for load balancers and monitoring."""
    from api.store import audit_records, configs

    return {
        "status": "healthy",
        "mode": "demo",
        "version": "0.1.0-alpha",
        "checks_available": ["entailment", "semantic_entropy", "implicit_preference", "claim_extraction"],
        "audit_records_stored": len(audit_records),
        "configs_stored": len(configs),
    }
