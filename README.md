# AgentGuard AI — ContextLock v1.0

A research prototype for **workflow-aware authorization of autonomous agent actions**. This release focuses on cumulative refund limits and pre-execution decision evidence. No real money moves.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
streamlit run app.py
```

Run automated tests without any third-party dependencies:

```bash
python3 -m unittest discover -s tests -v
```

## Demo

1. Click **Run refund splitting attack**.
2. Verify ₹6,000 and ₹3,000 are allowed, but ₹4,000 is blocked against a ₹10,000 cumulative case limit.
3. Inspect the decision evidence table.
4. Run the test suite, including eight concurrent refund attempts.

## Security design

- SQLite `BEGIN IMMEDIATE` serializes competing writes so simultaneous requests cannot exceed a shared case limit.
- Each action ID is idempotent; reusing the ID with different request data is denied.
- Mandates bind agent ID, case ID, cumulative limit, and expiry.
- Decision evidence includes a versioned rule identifier and decision reason.

## Critical limitations

- This is a **simulator**, not a real enforcement proxy or payment processor. `ALLOW` records a simulated refund atomically; it does not call an external API.
- Agent identity is caller-provided, not cryptographically authenticated.
- No human approval flow, production-change scenario, policy replay, cryptographic audit signing, or multi-service distributed transactions yet.
- SQLite is suitable for a local POC, not a horizontally scaled production service.
- The demo UI has no authentication. Do not expose it to the public Internet with real data.
- A production integration must ensure all protected actions traverse a trusted gateway and use transactional outbox / reservation-and-reconciliation patterns for downstream execution.

## Next iterations

- V1.1: FastAPI gateway, identity verification, staging/production scoped approval scenario.
- V1.2: Human approval, stronger evidence model, adversarial test matrix and benchmark report.
- V2: PostgreSQL, OPA integration, signed mandates, policy versioning and trace correlation.
