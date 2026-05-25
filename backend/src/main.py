import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.funds import router as funds_router
from src.api.holdings import router as holdings_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(title="主力风向标 (Main Force Radar)", version="0.1.0")

# R4 单用户、无认证,前端从任何 LAN IP 访问都允许。
# 同源走 vite proxy 时其实不需要 CORS,但加上做兜底:
# 1. 防止 iOS Safari 对同源 DELETE+Content-Type 的某些奇怪预检失败
# 2. 未来如果前端独立部署到不同 host,不用再改后端
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(funds_router)
app.include_router(holdings_router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "main-force-radar"}
