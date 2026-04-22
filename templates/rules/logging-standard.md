# Logging Standard

## Infrastructure

- **Sentry** — error/fatal (automatic exception capture)
- **Seq** — structured logs at all levels
- Languages: Node (pino), Python (structlog), C# (Serilog)

## Triggers: when to add logging

When writing code, **stop and think about logs** if you:

- Create an API endpoint → log entry and result (info)
- Call an external API/service → log request, response, duration_ms (info/error)
- Process a payment or money → log every step (info)
- Write a catch/except → log with context, don't swallow silently (error)
- Do file/S3 operations → log result (info/error)
- Write authorization/authentication → log attempts and result (info/warn)
- Start a background task/job → log start, completion, duration_ms (info)
- Invalidate cache → log key and reason (info)

## Rules

- **Context, not text:** `{ message: "Photo uploaded", context: { size_mb: 4.2, format: "webp" } }` — don't concatenate into a string
- **Always trace_id** to correlate requests across services
- **Measure duration_ms** on any I/O operations
- **NEVER:** passwords, tokens, card numbers, PII — only masked/hashed
- **Levels:** fatal/error → Sentry + Seq, warn/info → Seq, debug → dev only
