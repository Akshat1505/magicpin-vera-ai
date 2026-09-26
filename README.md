# VERA Growth Engine

A deterministic, context-grounded merchant AI assistant for the magicpin VERA challenge.

## Architecture
- `/v1/context`: versioned state store with idempotency/stale-version handling.
- `/v1/tick`: trigger routing, suppression, contextual composition, max 20 actions.
- `/v1/reply`: lightweight stateful conversation handling for action intent, auto-replies, questions and opt-outs.
- Category/merchant/customer/trigger context is never invented; messages use supplied facts.
- The decision layer is deterministic so identical inputs produce identical outputs.

## Run
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8080
```

## Deployment
Use the same command on Render, with the service port set to the platform's `$PORT` if required.
