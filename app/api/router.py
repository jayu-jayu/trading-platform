from fastapi import APIRouter
from app.api import auth, signals, prices, portfolio, backtest

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(signals.router)
api_router.include_router(prices.router)
api_router.include_router(portfolio.router)
api_router.include_router(backtest.router)
