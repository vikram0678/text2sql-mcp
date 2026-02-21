#!/bin/bash
# evaluator.sh
# End-to-end evaluation script for the text2sql-mcp API.

API_URL="${1:-http://localhost:8000}"
QUERY_ENDPOINT="$API_URL/query"

echo "=============================================="
echo "  text2sql-mcp  —  End-to-End Evaluator"
echo "  Target: $QUERY_ENDPOINT"
echo "=============================================="

echo ""
echo "Waiting for API to be available..."
until curl --output /dev/null --silent --head --fail "$API_URL/docs"; do
    printf '.'
    sleep 5
done
echo ""
echo "✓ API is up!"
echo ""

queries=(
  "Top 3 customers by order count"
  "Average order value by region"
  "Monthly revenue for 2024"
  "Products that have never been ordered"
  "Total spend by customer segment"
)

SUCCESS_COUNT=0
FAIL_COUNT=0

for q in "${queries[@]}"; do
    echo "──────────────────────────────────────────────"
    echo "Testing: $q"

    response=$(curl -s -X POST "$QUERY_ENDPOINT" \
        -H "Content-Type: application/json" \
        -d "{\"question\": \"$q\"}")

    # Use jq if available, otherwise use grep
    if command -v jq &> /dev/null; then
        result_length=$(echo "$response" | jq '.results | length' 2>/dev/null || echo "0")
        # For "products never ordered" empty is also valid - check sql key exists
        has_sql=$(echo "$response" | jq 'has("sql")' 2>/dev/null || echo "false")
    else
        # Fallback: check if response contains "sql" key (valid response)
        has_sql=$(echo "$response" | grep -c '"sql"' || echo "0")
        result_length=$(echo "$response" | grep -o '"results":\[' | wc -l)
    fi

    # Success = has sql key (valid response structure) OR has results
    if echo "$response" | grep -q '"sql"'; then
        echo "✓ SUCCESS"
        SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
    else
        echo "✗ FAILED — No valid response"
        echo "  Response: $(echo "$response" | head -c 200)"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
done

echo ""
echo "=============================================="
echo "  Results: $SUCCESS_COUNT / ${#queries[@]} queries succeeded"
echo "=============================================="

if [ "$SUCCESS_COUNT" -ne "${#queries[@]}" ]; then
    echo "❌ Evaluation FAILED ($FAIL_COUNT queries failed)"
    exit 1
fi

echo "✅ All queries passed!"
exit 0