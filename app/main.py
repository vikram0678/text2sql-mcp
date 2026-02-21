"""
text2sql-mcp — FastAPI entry point.
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.agent import run_agent
from app.mcp_server import MCPServer, MCPSecurityError

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App lifecycle – initialise MCP once at startup
# ---------------------------------------------------------------------------
mcp_server: MCPServer | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mcp_server
    db_url = os.environ.get("DATABASE_URL", "sqlite:///./data/sales.db")
    mcp_server = MCPServer(db_url)
    logger.info(f"MCPServer ready — connected to {db_url}")
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="text2sql-mcp",
    description=(
        "Natural language → SQL AI agent using Model Context Protocol (MCP) "
        "for secure, read-only SQLite access."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    question: str


class ChartData(BaseModel):
    labels: list[str]
    values: list[float]


class QueryResponse(BaseModel):
    sql: str
    results: list[dict[str, Any]]
    chart_data: ChartData


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", tags=["health"])
async def root():
    return {"status": "ok", "service": "text2sql-mcp"}


@app.get("/health", tags=["health"])
async def health():
    return {"status": "healthy"}


@app.post("/query", response_model=QueryResponse, tags=["query"])
async def query(request: QueryRequest):
    """
    Translate a natural language question into SQL, execute it against the
    sales database via MCP, and return the results plus chart-ready data.
    """
    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="Question must not be empty.")

    try:
        result = run_agent(request.question.strip(), mcp_server)
        return result
    except ValueError as e:
        # Unanswerable question or LLM returned garbage
        raise HTTPException(status_code=400, detail=str(e))
    except MCPSecurityError as e:
        raise HTTPException(status_code=400, detail=f"Security violation: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error for question: {request.question!r}")
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")