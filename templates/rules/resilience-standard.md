# Resilience Standard

## Triggers: when to think about fault tolerance

When writing code, **stop and think "what if it breaks?"** if you:

- Call an external API/service → what if timeout, 5xx, unavailable? Retry with backoff, circuit breaker, fallback
- Write to DB → what if constraint violation, deadlock, connection lost? Transactions, retry, graceful error
- Process a payment or multi-step operation → what if failure between steps? Idempotency, saga, compensation
- Work with files/S3 → what if partial write, disk full, permission denied? Atomic write (temp + rename), cleanup
- Start a background task/job → what if crash mid-job? Retry policy, checkpoint, dead letter queue
- Distributed operation → what if some nodes unavailable? Timeout, partial failure handling, eventual consistency
- Accept user input → what if invalid data, injection, overflow? Validate at boundary

## What to do when a trigger fires

1. **Identify failure mode** — what exactly can go wrong?
2. **Identify impact** — what happens to the user/system?
3. **Choose strategy:**
   - Retry (transient errors) — with exponential backoff and max attempts
   - Fallback (degraded mode) — return cached data, show placeholder
   - Circuit breaker (cascading failures) — stop calling the failed service
   - Compensation (partial failure) — roll back completed steps
   - Fail fast (unrecoverable) — return a clear error, don't hang
4. **Log it** — every failure path must be logged (see logging-standard)

## When NOT needed

- Configuration files, DTOs, models without logic
- UI components without server interaction
- Unit tests
- One-off scripts and migrations
- Internal pure functions without I/O
