---
name: integration-adapter
description: Mandatory pattern for adding ANY external service (WhatsApp, SMS, IVR, Bhashini, TTS, ABDM, eSanjeevani, 108, e-Hospital, e-RaktKosh, OSRM). Use whenever creating or modifying code that talks to a vendor API, telephony provider, or government system.
---

# Integration Adapter Pattern

Every external service is a swappable adapter. Business logic never imports a vendor SDK.

## Steps

1. **Interface first.** Define/extend the domain interface in `backend/app/adapters/base.py` (e.g. `MessagingAdapter.send(to, template, params) -> DeliveryResult`). Methods express OUR domain, not the vendor's API shape.
2. **Mock before real.** Create `adapters/<service>_mock.py` FIRST. The mock must:
   - persist real rows (e.g. `notifications` with `mock=true`) so demos show real data,
   - simulate realistic latency (50–300ms) and an occasional failure path,
   - log to the dev outbox so the UI can display "sent" messages.
3. **Real second (only if credentials exist).** `adapters/<service>_real.py` with retry (3x, exponential backoff), timeout ≤ 5s, and error mapping to our `AdapterError` types. A real-adapter failure must degrade, never crash a flow: log, mark FAILED, continue.
4. **Factory + flag.** Register in `adapters/factory.py`; selection via `<SERVICE>_MOCK_MODE` env var, **default `true`**. Add both vars to `.env.example` with a comment.
5. **Contract test.** One test file runs the same test suite against mock (always) and real (skipped unless creds present) to guarantee they behave identically.
6. **Docs.** Add the service to the adapter table in `docs/ARCHITECTURE.md` if new.

## Hard rules

- Default is ALWAYS mock. The demo must never depend on vendor uptime, venue internet, or account approval.
- Never put vendor payload shapes in `services/` — translate at the adapter boundary.
- Tier 3 integrations (ABDM production, live eSanjeevani/108/e-Hospital) get interface + mock ONLY. Building a real adapter for them violates CLAUDE.md §NEVER BUILD.
