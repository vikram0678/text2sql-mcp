"""
Pytest tests for the text2sql-mcp /query endpoint and MCP server security.
Run inside the container: docker-compose exec api pytest
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.mcp_server import MCPServer, MCPSecurityError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """FastAPI test client with lifespan (startup/shutdown) executed."""
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def mcp():
    return MCPServer("sqlite:///./data/sales.db")


# ---------------------------------------------------------------------------
# /query endpoint tests
# ---------------------------------------------------------------------------

class TestQueryEndpoint:

    def test_health_check(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    def test_total_customers(self, client):
        """Core requirement: total customers must be 500."""
        resp = client.post("/query", json={"question": "What is the total number of customers?"})
        assert resp.status_code == 200
        body = resp.json()
        assert "sql" in body
        assert "results" in body
        assert "chart_data" in body
        assert len(body["results"]) > 0
        # The single result row should contain the value 500
        row = body["results"][0]
        count_value = list(row.values())[0]
        assert int(count_value) == 500, f"Expected 500 customers, got {count_value}"

    def test_response_schema(self, client):
        """Verify all required keys and nested structure are present."""
        resp = client.post("/query", json={"question": "How many orders are there?"})
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["sql"], str)
        assert isinstance(body["results"], list)
        assert isinstance(body["chart_data"], dict)
        assert "labels" in body["chart_data"]
        assert "values" in body["chart_data"]
        assert isinstance(body["chart_data"]["labels"], list)
        assert isinstance(body["chart_data"]["values"], list)

    def test_sql_is_select(self, client):
        """Generated SQL must be a SELECT statement."""
        resp = client.post("/query", json={"question": "List all product categories"})
        assert resp.status_code == 200
        sql = resp.json()["sql"].strip().upper()
        assert sql.startswith("SELECT"), f"Expected SELECT, got: {sql[:30]}"

    def test_complex_join_query(self, client):
        """Technology revenue query requiring joins."""
        resp = client.post(
            "/query",
            json={"question": "What is the total revenue from the Technology category?"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["results"]) > 0

    def test_unanswerable_question_returns_error(self, client):
        """Irrelevant questions must return a non-200 status."""
        resp = client.post("/query", json={"question": "What is the weather like today?"})
        assert resp.status_code in (400, 422, 500)
        body = resp.json()
        assert "detail" in body or "error" in body

    def test_empty_question_returns_400(self, client):
        resp = client.post("/query", json={"question": ""})
        assert resp.status_code == 400

    def test_missing_question_field_returns_422(self, client):
        resp = client.post("/query", json={})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# MCP Server security tests
# ---------------------------------------------------------------------------

class TestMCPSecurity:

    def test_list_tables_returns_expected_tables(self, mcp):
        tables = mcp.list_tables()
        assert set(tables) >= {"customers", "orders", "products", "order_items"}

    def test_describe_schema_customers(self, mcp):
        cols = mcp.describe_schema("customers")
        col_names = [c["name"] for c in cols]
        assert "id" in col_names
        assert "name" in col_names
        assert "region" in col_names
        assert "segment" in col_names

    def test_describe_schema_invalid_table(self, mcp):
        with pytest.raises(RuntimeError):
            mcp.describe_schema("nonexistent_table")

    def test_execute_select_works(self, mcp):
        rows = mcp.execute_query("SELECT COUNT(*) AS n FROM customers")
        assert len(rows) == 1
        assert int(list(rows[0].values())[0]) == 500

    def test_execute_drop_rejected(self, mcp):
        with pytest.raises(MCPSecurityError):
            mcp.execute_query("DROP TABLE customers")

    def test_execute_delete_rejected(self, mcp):
        with pytest.raises(MCPSecurityError):
            mcp.execute_query("DELETE FROM customers WHERE id = 1")

    def test_execute_update_rejected(self, mcp):
        with pytest.raises(MCPSecurityError):
            mcp.execute_query("UPDATE customers SET name='x' WHERE id=1")

    def test_execute_insert_rejected(self, mcp):
        with pytest.raises(MCPSecurityError):
            mcp.execute_query("INSERT INTO customers VALUES (999,'x','y','z')")

    def test_execute_comment_bypass_rejected(self, mcp):
        """SQL comment tricks must not bypass the SELECT-only check."""
        with pytest.raises(MCPSecurityError):
            mcp.execute_query("-- harmless comment\nDROP TABLE customers")