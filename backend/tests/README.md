# Tests

## Running tests

```bash
# All tests (needs running backend at localhost:8001)
REACT_APP_BACKEND_URL=http://localhost:8001 python -m pytest . -v

# Single file
python -m pytest test_bot_multiplataforma.py -v --timeout=30
```

## Structure

| File | Coverage |
|------|---------|
| `test_bot_multiplataforma.py` | Core: health, auth, webhooks, E1 console, credits |
| `legacy/test_iteration_*.py` | Historical iteration tests (kept for reference) |

## Configuration

`conftest.py` sets `asyncio_mode = "auto"` for async test support.

Tests hit a **live HTTP server** — `REACT_APP_BACKEND_URL` must point to a running backend.
For CI, the workflow starts uvicorn before running tests.
