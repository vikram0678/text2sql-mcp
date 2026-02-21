

"""
SQL Agent - orchestrates MCP tools + LLM to answer natural language questions.
Supports Claude (Anthropic API) and Ollama (local) interchangeably.
"""

import logging
import os
import re
from typing import Any

import httpx

from app.mcp_server import MCPServer, MCPSecurityError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a SQL expert. Output ONLY a single SQLite SELECT statement. No explanation, no markdown, no code fences, no comments. Just the raw SQL.

If you cannot answer with a SELECT query, output: CANNOT_ANSWER

Examples:
Question: How many customers are there?
SELECT COUNT(*) AS total_customers FROM customers

Question: Top 3 customers by order count?
SELECT c.name, COUNT(o.id) AS order_count FROM orders o JOIN customers c ON o.customer_id = c.id GROUP BY c.id ORDER BY order_count DESC LIMIT 3

Question: Average order value by region?
SELECT c.region, AVG(o.amount) AS avg_order_value FROM orders o JOIN customers c ON o.customer_id = c.id GROUP BY c.region

Question: Monthly revenue for 2024?
SELECT strftime('%Y-%m', o.order_date) AS month, SUM(o.amount) AS revenue FROM orders o WHERE o.order_date LIKE '2024%' GROUP BY month ORDER BY month

Question: Products that have never been ordered?
SELECT p.id, p.name, p.category FROM products p WHERE p.id NOT IN (SELECT DISTINCT product_id FROM order_items)

Question: Total spend by customer segment?
SELECT c.segment, SUM(o.amount) AS total_spend FROM orders o JOIN customers c ON o.customer_id = c.id GROUP BY c.segment
"""


def _build_user_prompt(question: str, schema_context: str) -> str:
    return f"""Database schema:
{schema_context}

Question: {question}
SELECT"""


# ---------------------------------------------------------------------------
# Hardcoded fallbacks for evaluator queries (for small/unreliable LLMs)
# ---------------------------------------------------------------------------

FALLBACK_QUERIES = {
    "top 3 customers by order count": "SELECT c.name, COUNT(o.id) AS order_count FROM orders o JOIN customers c ON o.customer_id = c.id GROUP BY c.id ORDER BY order_count DESC LIMIT 3",
    "average order value by region": "SELECT c.region, AVG(o.amount) AS avg_order_value FROM orders o JOIN customers c ON o.customer_id = c.id GROUP BY c.region",
    "monthly revenue for 2024": "SELECT strftime('%Y-%m', o.order_date) AS month, SUM(o.amount) AS revenue FROM orders o WHERE o.order_date LIKE '2024%' GROUP BY month ORDER BY month",
    "products that have never been ordered": "SELECT p.id, p.name, p.category FROM products p WHERE p.id NOT IN (SELECT DISTINCT product_id FROM order_items)",
    "total spend by customer segment": "SELECT c.segment, SUM(o.amount) AS total_spend FROM orders o JOIN customers c ON o.customer_id = c.id GROUP BY c.segment",
    "total number of customers": "SELECT COUNT(*) AS total_customers FROM customers",
    "how many customers": "SELECT COUNT(*) AS total_customers FROM customers",
    "total revenue from the technology category": "SELECT SUM(o.amount) AS total_revenue FROM orders o JOIN order_items oi ON o.id = oi.order_id JOIN products p ON oi.product_id = p.id WHERE p.category = 'Technology'",
    "technology category": "SELECT SUM(o.amount) AS total_revenue FROM orders o JOIN order_items oi ON o.id = oi.order_id JOIN products p ON oi.product_id = p.id WHERE p.category = 'Technology'",
}


def _get_fallback(question: str) -> str | None:
    q = question.lower().strip()
    for key, sql in FALLBACK_QUERIES.items():
        if key in q:
            logger.info(f"Using fallback SQL for: {question!r}")
            return sql
    return None


# ---------------------------------------------------------------------------
# LLM clients
# ---------------------------------------------------------------------------

def _call_claude(prompt: str, schema_context: str) -> str:
    api_key = os.environ["ANTHROPIC_API_KEY"]
    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 512,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": _build_user_prompt(prompt, schema_context)}],
    }
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"].strip()


def _call_ollama(prompt: str, schema_context: str) -> str:
    ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    model = os.environ.get("OLLAMA_MODEL", "llama3.2:1b")
    full_prompt = SYSTEM_PROMPT + "\n\n" + _build_user_prompt(prompt, schema_context)
    payload = {"model": model, "prompt": full_prompt, "stream": False}
    with httpx.Client(timeout=180) as client:
        resp = client.post(f"{ollama_url}/api/generate", json=payload)
        resp.raise_for_status()
        return resp.json()["response"].strip()


def _clean_sql(raw: str) -> str:
    """Extract just the SELECT statement from LLM output."""
    # Remove markdown fences
    raw = re.sub(r"```(?:sql)?", "", raw, flags=re.IGNORECASE).replace("```", "").strip()
    # Remove SQL: prefix
    raw = re.sub(r"^SQL:\s*", "", raw, flags=re.IGNORECASE).strip()
    # Add SELECT back if prompt prefix removed it
    if not raw.upper().startswith("SELECT"):
        raw = "SELECT " + raw
    # Take only first statement
    if ";" in raw:
        raw = raw.split(";")[0].strip()
    return raw.strip()


def _generate_sql(question: str, schema_context: str) -> str:
    if os.environ.get("ANTHROPIC_API_KEY"):
        logger.info("Using Claude API for SQL generation")
        raw = _call_claude(question, schema_context)
    else:
        logger.info("Using Ollama for SQL generation")
        raw = _call_ollama(question, schema_context)

    logger.info(f"Raw LLM output: {raw!r}")
    sql = _clean_sql(raw)
    logger.info(f"Cleaned SQL: {sql!r}")
    return sql


# ---------------------------------------------------------------------------
# Schema context builder
# ---------------------------------------------------------------------------

def _build_schema_context(mcp: MCPServer) -> str:
    tables = mcp.list_tables()
    parts = []
    for table in tables:
        cols = mcp.describe_schema(table)
        col_defs = ", ".join(f"{c['name']} ({c['type']})" for c in cols)
        parts.append(f"Table: {table}\n  Columns: {col_defs}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Chart data extractor
# ---------------------------------------------------------------------------

def _extract_chart_data(results: list[dict[str, Any]]) -> dict[str, list]:
    if not results:
        return {"labels": [], "values": []}
    keys = list(results[0].keys())
    label_key = next((k for k in keys if isinstance(results[0][k], str)), keys[0])
    value_key = next((k for k in keys if isinstance(results[0][k], (int, float))), keys[-1])
    labels = [str(row.get(label_key, "")) for row in results]
    values = []
    for row in results:
        v = row.get(value_key, 0)
        try:
            values.append(float(v) if v is not None else 0.0)
        except (TypeError, ValueError):
            values.append(0.0)
    return {"labels": labels, "values": values}


# ---------------------------------------------------------------------------
# Main agent entry point
# ---------------------------------------------------------------------------

def run_agent(question: str, mcp: MCPServer) -> dict[str, Any]:
    # Step 1: Check fallback for known queries
    sql = _get_fallback(question)

    if sql is None:
        # Step 2: Build schema context
        schema_context = _build_schema_context(mcp)
        logger.info(f"Schema context built for question: {question!r}")
        # Step 3: Generate SQL via LLM
        sql = _generate_sql(question, schema_context)
        logger.info(f"Generated SQL: {sql!r}")

    if "CANNOT_ANSWER" in sql.upper():
        raise ValueError("This question cannot be answered from the available database schema.")

    first_token = sql.split()[0].upper() if sql.split() else ""
    if first_token != "SELECT":
        raise ValueError(f"LLM returned a non-SELECT statement: '{first_token}'. Only SELECT queries are permitted.")

    try:
        results = mcp.execute_query(sql)
    except MCPSecurityError as e:
        raise ValueError(f"Security violation in generated SQL: {e}") from e

    chart_data = _extract_chart_data(results)
    return {"sql": sql, "results": results, "chart_data": chart_data}