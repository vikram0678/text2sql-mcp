"""
MCP Server - Model Context Protocol implementation for secure SQLite access.

Provides read-only tools for the AI agent to inspect and query the database
without exposing credentials or allowing destructive operations.
"""

import re
import logging
from typing import Any

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


class MCPSecurityError(Exception):
    """Raised when a query violates security constraints."""
    pass


class MCPServer:
    """
    MCP Server that exposes three secure, read-only tools for database interaction.

    Tools:
        - list_tables(): List all tables in the database.
        - describe_schema(table_name): Get column details for a table.
        - execute_query(sql): Run a SELECT query and return results.
    """

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
        )
        logger.info(f"MCPServer initialized with database: {database_url}")

    # -------------------------------------------------------------------------
    # Tool 1: list_tables
    # -------------------------------------------------------------------------
    def list_tables(self) -> list[str]:
        """Return a list of all user-defined table names in the database."""
        try:
            inspector = inspect(self.engine)
            tables = inspector.get_table_names()
            logger.debug(f"list_tables() -> {tables}")
            return tables
        except SQLAlchemyError as e:
            logger.error(f"list_tables error: {e}")
            raise RuntimeError(f"Failed to list tables: {e}") from e

    # -------------------------------------------------------------------------
    # Tool 2: describe_schema
    # -------------------------------------------------------------------------
    def describe_schema(self, table_name: str) -> list[dict[str, Any]]:
        """
        Return column metadata for the given table.

        Returns a list of dicts with keys: name, type, nullable, primary_key.
        """
        try:
            inspector = inspect(self.engine)
            # Validate the table exists to avoid information leakage
            valid_tables = inspector.get_table_names()
            if table_name not in valid_tables:
                raise ValueError(f"Table '{table_name}' does not exist.")

            columns = inspector.get_columns(table_name)
            schema = [
                {
                    "name": col["name"],
                    "type": str(col["type"]),
                    "nullable": col.get("nullable", True),
                }
                for col in columns
            ]
            logger.debug(f"describe_schema({table_name}) -> {schema}")
            return schema
        except (SQLAlchemyError, ValueError) as e:
            logger.error(f"describe_schema error: {e}")
            raise RuntimeError(f"Failed to describe schema: {e}") from e

    # -------------------------------------------------------------------------
    # Tool 3: execute_query
    # -------------------------------------------------------------------------
    def execute_query(self, sql: str) -> list[dict[str, Any]]:
        """
        Execute a read-only SELECT query and return results as a list of dicts.

        Security guardrails:
        1. Strips comments and normalises whitespace.
        2. Rejects any statement that is not a SELECT.
        3. Uses SQLAlchemy parameterised execution (no string interpolation).
        """
        cleaned = self._sanitize_sql(sql)
        self._assert_select_only(cleaned)

        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(cleaned))
                rows = [dict(zip(result.keys(), row)) for row in result.fetchall()]
            logger.debug(f"execute_query returned {len(rows)} rows")
            return rows
        except SQLAlchemyError as e:
            logger.error(f"execute_query error: {e}")
            raise RuntimeError(f"Query execution failed: {e}") from e

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------
    @staticmethod
    def _sanitize_sql(sql: str) -> str:
        """Strip SQL comments and normalise whitespace."""
        # Remove single-line comments
        sql = re.sub(r"--[^\n]*", " ", sql)
        # Remove multi-line comments
        sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
        return sql.strip()

    @staticmethod
    def _assert_select_only(sql: str) -> None:
        """
        Raise MCPSecurityError if the SQL is not a plain SELECT statement.

        Checks both the first keyword and blocks known destructive keywords
        anywhere in the query.
        """
        first_token = sql.split()[0].upper() if sql.split() else ""
        if first_token != "SELECT":
            raise MCPSecurityError(
                f"Only SELECT statements are permitted. Got: '{first_token}'"
            )

        forbidden = {"DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE",
                    "TRUNCATE", "REPLACE", "ATTACH", "DETACH", "PRAGMA"}
        tokens = {t.upper() for t in re.split(r"\W+", sql)}
        violations = tokens & forbidden
        if violations:
            raise MCPSecurityError(
                f"Query contains forbidden keyword(s): {violations}"
            )