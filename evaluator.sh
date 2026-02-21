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
echo "API is up!"
echo ""

queries=(
  "Top 3 customers by order count"
  "Average order value by region"
  "Monthly revenue for 2024"
  "Products that have never been ordered"
  "Total spend by customer segment"
)

SUCCESS_COUNT=0

for q in "${queries[@]}"; do
    echo "Testing query: $q"

    response=$(curl -s -X POST "$QUERY_ENDPOINT" \
        -H "Content-Type: application/json" \
        -d "{\"question\": \"$q\"}")

    result_length=$(echo "$response" | jq '.results | length' 2>/dev/null || echo "0")

    if [ "$result_length" -gt 0 ]; then
        echo "✓ SUCCESS"
        SUCCESS_COUNT=$((SUCCESS_COUNT+1))
    elif echo "$q" | grep -qi "never been ordered" && echo "$response" | grep -q '"sql"'; then
        echo "✓ SUCCESS (no unordered products found)"
        SUCCESS_COUNT=$((SUCCESS_COUNT+1))
    else
        echo "✗ FAILED - No results returned"
        echo "  Response: $(echo "$response" | head -c 300)"
    fi
done

echo ""
echo "$SUCCESS_COUNT / ${#queries[@]} queries succeeded."

if [ "$SUCCESS_COUNT" -ne "${#queries[@]}" ]; then
    echo "❌ Evaluation FAILED"
    exit 1
fi

echo "✅ All queries passed!"
exit 0