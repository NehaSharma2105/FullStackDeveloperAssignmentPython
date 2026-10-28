# Written answers

Interpretations used for the implementation are listed at the end. Section 3 answers are Questions A and B (200–350 words each). Question C is omitted.

---

## Section 1 — Root cause and fix (summary)

**Category:** N+1 / related-object ORM queries.

The view still does `Order.objects.filter(customer_id=...)`. After the deploy, the dashboard serializer reads `order.customer`, `order.items.all()`, and `item.product`. Those attributes are lazy. Django issues a new `SELECT` per instance unless the queryset was prepared with `select_related` / `prefetch_related`. Query count therefore grows with the customer’s order (and line-item) count, which matches “only users with 200+ orders time out.”

**Fix:** `optimized_orders_queryset` uses `select_related("customer")` (JOIN on a `ForeignKey`) and `prefetch_related("items__product")` (one `IN` query for items, one for products, results cached on the parent). Reproduce with `?naive=1` vs the default path. Investigation narrative: `docs/incident-log.md`.

---

## Section 2 — SIGKILL of an in-flight Celery worker

If the worker is SIGKILL’d mid-task, the OS does not run `try/finally` in that process. With **`task_acks_late=True`** (also `CELERY_TASK_ACKS_LATE`), Celery has **not** ACK’d the Redis list/stream message, so the job is still in the broker’s unacked set.

The Redis transport exposes that message again after **`visibility_timeout`** (`CELERY_BROKER_TRANSPORT_OPTIONS["visibility_timeout"]`, 3600s here). Another worker then executes `send_transactional_email` again. **`task_reject_on_worker_lost=True`** asks Celery to requeue rather than treat worker loss as success.

Consequences: the email provider may already have accepted the message. This design is **at-least-once**. We make retries safe by storing `EmailJob.status` under `select_for_update` and returning `duplicate_skipped` if the row is already `sent`, and by passing `idempotency_key` into the fake provider. Exactly-once delivery would require the **vendor** to honour that key. Prefetch is 1 so a killed worker does not hide a large reserved batch.

Rate-limit tokens are consumed at admit-time. A kill after admit and before send wastes a slot in the 60s window; we accept that rather than send without a token.

---

## Section 3 — Question A — Django Admin performance

A primary-key index does not make `ModelAdmin` changelists cheap at 500,000 rows. Three other causes I would measure next:

**1. `COUNT(*)` on every changelist.** `ChangeList` uses Django’s `Paginator`, which calls `QuerySet.count()` so the footer can show “1–100 of 500000.” On a fat table that is a sequential scan even when the page query is an index range. **Fix:** set `show_full_result_count = False` on the `ModelAdmin`. Django then skips the full count and shows a page-has-next estimate. You sacrifice an exact total; you gain a changelist that scales.

**2. Related objects in `list_display` without `list_select_related`.** If `list_display` includes a `ForeignKey` (or a method that touches one), each row does `obj.fk.field`. That is the admin N+1. **Fix:** `list_select_related = ("customer",)` or override `get_queryset()` with `select_related` / `prefetch_related`. For reverse relations or M2M, `list_select_related` cannot JOIN correctly; use `prefetch_related` in `get_queryset`. Also avoid calling `.count()` of children per row in a `list_display` method; annotate with `Count("items")` instead.

**3. Unbounded `list_per_page` and unindexed `search_fields`.** Default `list_per_page` is 100; some teams raise it to 1,000, which multiplies serializer/template work and sort cost. `search_fields = ("email", "name")` compiles to `WHERE ... ILIKE '%term%'` (`icontains`). Leading-wildcard `LIKE` cannot use a normal B-tree. **Fix:** keep `list_per_page` modest (50–100), add `list_filter` only on selective indexed columns, and prefer `istartswith` or a dedicated search vector/trigram index if search is required. `date_hierarchy` on an unindexed datetime will also sort the whole table; index that field if you keep the hierarchy.

I would confirm each with Silk or `connection.queries` on `/admin/app/model/` before changing indexes blindly.

---

## Section 3 — Question B — Pagination trade-offs

Offset pagination (`LIMIT n OFFSET k`, DRF `LimitOffsetPagination` / `PageNumberPagination`) is simple for jump-to-page UIs. At scale the database still **walks and discards** `k` rows. Page 1,000 of 10 items is not “10 index reads”; it is a scan of 10,000 ordered rows plus a filter. Deep mobile infinite scroll therefore gets slower every page. If rows are inserted or deleted while the user scrolls, offset windows **shift**: a new order at the top duplicates an item the client already saw, or a deletion skips one. Stable `ordering = ("id",)` does not fix that; it only makes the scan deterministic.

Cursor pagination (DRF `CursorPagination`, keyset `WHERE (placed_at, id) < (last_ts, last_id) ORDER BY placed_at DESC, id DESC LIMIT n`) seeks into the index and reads the next n rows. Time per page stays flat. Infinite scroll maps naturally to an opaque cursor. Mutations are kinder: a newly inserted row appears on a later refresh, not as a duplicated “page 3.” You **cannot** jump to page 47 without walking 47 pages. You **must** order by a unique, stable tuple; `ORDER BY placed_at` alone is wrong if two orders share a timestamp. DRF cursors are signed and opaque, which is good for not letting clients invent offsets, but bad if the app must show “page 12 of 400.”

I would use **cursor** for the mobile dashboard’s infinite order list (high churn, only “next”). I would use **offset/page numbers** for an internal admin export UI that needs “go to page 9,” with a hard `max_limit` and a covering index on the order key. Mixing both without telling clients which `ordering` is required will produce duplicate or missing rows either way.

---

## Interpretations

- “200 emails per minute” is implemented as **200 admits per rolling 60 seconds**, not a wall-clock minute bucket.
- Emails are sent only through `FakeEmailProvider`; no SMTP.
- SQLite is the local database so the project starts in under five minutes; PostgreSQL would be the production default.
- Section 4 (Loom) is not included unless a recording link is added later.
