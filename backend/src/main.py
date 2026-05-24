import logging

from fastapi import FastAPI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(title="主力风向标 (Main Force Radar)", version="0.1.0")


@app.get("/health")
def health():
    return {"status": "ok", "service": "main-force-radar"}
