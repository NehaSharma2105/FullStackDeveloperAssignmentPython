# Section 1 — Incident investigation log

Scenario: `/api/orders/summary/` used to return in ~80ms. After a routine deploy it times out (30s+) for customers with 200+ orders. The view function body was not edited.

## Ordered investigation

1. **Reproduce with a known heavy customer.** Seed 220 orders × 3 line items (`python manage.py seed_orders`). Hit `GET /api/orders/summary/?customer_id=<id>&naive=1`. If only “power users” fail, the work scales with *that customer’s* related rows, not with a global lock or a downed service.

2. **Rule out the obvious infrastructure layer.** Process is up, SQLite/Postgres is reachable, CPU is not pegged before the request starts returning rows. A 30s timeout that tracks order count is rarely “Redis is down”; it is usually per-row work in the request thread.

3. **Count SQL, do not guess.** With `DEBUG=True`, wrap the request in `CaptureQueriesContext` (and later Silk at `/silk/`). A healthy summary of N orders with line items should be a handful of statements (orders JOIN customer, prefetch items, prefetch products). If the count is `O(orders)` or `O(line items)`, it is an ORM evaluation problem, not a missing primary-key index. Primary keys are already indexed.

4. **Inspect the statements, not just the count.** Silk’s query list shows repeated `SELECT` on `orders_customer`, `orders_orderitem`, and `orders_product` with a changing `id = %s`. That pattern is lazy related-object access: `order.customer`, `order.items.all()`, `item.product` on a queryset that only did `Order.objects.filter(...)`.

5. **Ask what changed if the view file did not.** Typical deploy-adjacent causes: a serializer started embedding line items for the mobile dashboard; a `SerializerMethodField` started reading `item.product.sku`; a model gained a new `ForeignKey` that templates/admin already touched. The queryset in the view stayed `Order.objects.filter(customer_id=...)`, so code review of that one file misses the regression.

6. **Reject competing categories with evidence.**
   - Missing index on PK: Django already has one; `EXPLAIN` would show PK lookups, not hundreds of them.
   - Cache invalidation: there is no cache on this endpoint.
   - Serializer CPU without SQL: Silk would show few queries and high Python time. We see many queries.

## Root-cause category

**N+1 (actually N× related) queries from lazy ORM access**, triggered when the summary serializer walks `ForeignKey` and reverse-`ForeignKey` relations that the view queryset does not cache.

## Fix

`select_related("customer")` for the forward FK (SQL `JOIN`). `prefetch_related("items__product")` for reverse FK + nested product FK (one items query, one products query, Django’s prefetch cache). See `apps/orders/querysets.py`.

## Evidence

Do not invent numbers. After migrate + seed, run:

```powershell
.\.venv\Scripts\python.exe scripts\capture_query_counts.py
```

Then start the server, hit naive and optimized URLs, and compare SQL counts in Silk (`/silk/`). Record the output in `docs/query-counts.txt` on the machine that ran the script.
