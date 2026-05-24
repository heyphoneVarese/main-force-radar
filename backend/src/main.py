import logging

from fastapi import FastAPI

from src.api.funds import router as funds_router
from src.api.holdings import router as holdings_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(title="主力风向标 (Main Force Radar)", version="0.1.0")
app.include_router(funds_router)
app.include_router(holdings_router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "main-force-radar"}
