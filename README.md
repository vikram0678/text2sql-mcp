# text2sql-mcp

> Natural language → SQL AI agent using Model Context Protocol (MCP) for secure, read-only SQLite access.

---

## What is this?

`text2sql-mcp` lets you ask questions in plain English about a sales database and get back structured data — no SQL knowledge required.

**Example:**
```
You ask:  "What are the top 3 customers by order count?"
App returns:
{
  "sql": "SELECT c.name, COUNT(o.id) AS order_count FROM orders o JOIN customers c ...",
  "results": [{"name": "Customer 499", "order_count": 5}, ...],
  "chart_data": {"labels": ["Customer 499", ...], "values": [5, ...]}
}
```

---

## Architecture

```
┌─────────────────────────────────────────┐
│           FastAPI (main.py)             │
│         POST /query endpoint            │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│         SQL Agent (agent.py)            │
│  1. Get schema from MCP                 │
│  2. Send question + schema to LLM       │
│  3. Receive SQL from LLM                │
│  4. Execute SQL via MCP                 │
│  5. Return results + chart_data         │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│       MCP Server (mcp_server.py)        │
│  • list_tables()                        │
│  • describe_schema(table_name)          │
│  • execute_query(sql) ← SELECT only     │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│        SQLite (data/sales.db)           │
└─────────────────────────────────────────┘
         │
         ├── Claude API (if ANTHROPIC_API_KEY is set)
         └── Ollama / llama3.2:1b (free local fallback)
```

---

## Database Schema

| Table | Columns |
|-------|---------|
| `customers` | id, name, region, segment |
| `orders` | id, customer_id, amount, order_date |
| `products` | id, name, category, price |
| `order_items` | order_id, product_id, quantity |

500 customers · 30 products · ~1,500 orders

---

## Project Structure

```
text2sql-mcp/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI routes
│   ├── agent.py         # LLM + SQL generation logic
│   └── mcp_server.py    # MCP tools (secure DB access)
├── tests/
│   └── test_query.py    # Pytest tests
├── data/
│   └── sales.db         # SQLite database
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── evaluator.sh
├── .env.example
└── README.md
```

---

## Quick Start

### Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (running)
- [Ollama](https://ollama.com) installed + model pulled (free, no API key needed)
- OR an Anthropic API key for Claude

### 1. Clone the repo
```bash
git clone https://github.com/vikram0678/text2sql-mcp.git
cd text2sql-mcp
```

### 2. Set up environment
```bash
cp .env.example .env
# Open .env and fill in your values
```

### 3. Pull Ollama model (if using Ollama)
```bash
ollama pull llama3.2:1b
```

### 4. Start Ollama (Windows — run in PowerShell)
```powershell
$env:OLLAMA_HOST="0.0.0.0:11434"; ollama serve
```


### 5. Start the app
```bash
docker-compose up --build
```

### 6. Test it
Open your browser: **http://localhost:8000/docs**

Or via curl:
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "How many customers are there?"}'
```

Expected response:
```json
{
  "sql": "SELECT COUNT(*) AS total_customers FROM customers",
  "results": [{"total_customers": 500}],
  "chart_data": {"labels": ["500"], "values": [500.0]}
}
```

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Claude API key. Leave empty to use Ollama | `` |
| `DATABASE_URL` | SQLite database path inside container | `sqlite:///./data/sales.db` |
| `OLLAMA_URL` | Ollama server URL | `http://host.docker.internal:11434` |
| `OLLAMA_MODEL` | Ollama model to use | `llama3.2:1b` |

---

## API Reference

### `POST /query`

**Request:**
```json
{
  "question": "What is the total revenue by region?"
}


```
<!-- 
**Response (200 OK):**
```json
{
  "sql": "SELECT c.region, SUM(o.amount) AS total_revenue FROM ...",
  "results": [
    {"region": "North", "total_revenue": 125430.50},
    {"region": "South", "total_revenue": 98765.25}
  ],
  "chart_data": {
    "labels": ["North", "South"],
    "values": [125430.50, 98765.25]
  }
} -->
```

**Error (400):** Question cannot be answered from schema
**Error (500):** Unexpected server error

### `GET /health`
Returns `{"status": "healthy"}`

---

## Running Tests

```bash
# Run inside the Docker container
docker-compose exec api pytest -v
```

---

## End-to-End Evaluation

```bash
bash evaluator.sh
```

Runs 5 predefined sales queries and checks all return valid responses:
- Top 3 customers by order count
- Average order value by region
- Monthly revenue for 2024
- Products that have never been ordered
- Total spend by customer segment

---

## Security

- **SELECT-only enforcement** — MCP server rejects any non-SELECT statement
- **Comment stripping** — SQL comments stripped before validation to prevent bypass tricks
- **Read-only volume** — database mounted as `ro` in Docker
- **Non-root container** — app runs as unprivileged user
- **No credentials in prompts** — LLM never sees database connection string

---

## LLM Support

| Provider | Setup | Quality |
|----------|-------|---------|
| Claude Haiku (Anthropic) | Set `ANTHROPIC_API_KEY` in `.env` | ⭐⭐⭐⭐⭐ |
| llama3.2:1b (Ollama) | Free, runs locally | ⭐⭐⭐ |
| llama3 (Ollama) | Free, runs locally, needs more RAM | ⭐⭐⭐⭐ |

---

<!-- ## License

MIT -->