"""
Standalone FastAPI app to test the Razorpay integration before backend/main.py
exists (Phase 2 Task 12 will build the real main.py and register payments router).

Run: uvicorn backend.payments_test_app:app --reload --port 8000
Open: http://localhost:8000/
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from backend.routers.payments import router as payments_router

app = FastAPI(title="Vachanam Razorpay Test", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(payments_router, prefix="/api", tags=["payments"])

_STATIC_DIR = Path(__file__).parent / "static"
_LANDING_PATH = _STATIC_DIR / "index.html"
_DEV_TEST_PATH = _STATIC_DIR / "razorpay-test.html"


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the Vachanam landing page with Razorpay-wired pricing buttons."""
    if _LANDING_PATH.exists():
        return FileResponse(_LANDING_PATH)
    return HTMLResponse("<h1>index.html not found</h1>", status_code=404)


@app.get("/dev/test", response_class=HTMLResponse)
async def dev_test():
    """Simple developer test page with a single Pay button (any amount)."""
    if _DEV_TEST_PATH.exists():
        return FileResponse(_DEV_TEST_PATH)
    return HTMLResponse("<h1>razorpay-test.html not found</h1>", status_code=404)


@app.get("/health")
async def health():
    return {"status": "ok"}
