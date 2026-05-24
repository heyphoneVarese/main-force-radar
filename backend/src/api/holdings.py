"""holdings CRUD endpoints。强 FK 校验:fund_code 必须先在 funds 表存在。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db import get_session
from src.models import Fund, Holding
from src.schemas.holdings import HoldingCreate, HoldingResponse, HoldingUpdate
from src.utils.money import int_to_nav, int_to_shares, nav_to_int, shares_to_int

router = APIRouter(prefix="/api/holdings", tags=["holdings"])


def _to_response(h: Holding) -> HoldingResponse:
    return HoldingResponse(
        id=h.id,
        fund_code=h.fund_code,
        cost_nav=int_to_nav(h.cost_nav_x10000),
        shares=int_to_shares(h.shares_x100),
        bought_at=h.bought_at,
        note=h.note,
        created_at=h.created_at,
        updated_at=h.updated_at,
    )


@router.get("", response_model=list[HoldingResponse])
def list_holdings(db: Session = Depends(get_session)):
    holdings = db.scalars(select(Holding).order_by(Holding.fund_code))
    return [_to_response(h) for h in holdings]


@router.get("/{fund_code}", response_model=HoldingResponse)
def get_holding(fund_code: str, db: Session = Depends(get_session)):
    h = db.scalar(select(Holding).where(Holding.fund_code == fund_code))
    if h is None:
        raise HTTPException(status_code=404, detail=f"holding for {fund_code} not found")
    return _to_response(h)


@router.post("", response_model=HoldingResponse, status_code=status.HTTP_201_CREATED)
def create_holding(payload: HoldingCreate, db: Session = Depends(get_session)):
    # 强校验:fund 必须存在
    if db.get(Fund, payload.fund_code) is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"fund_code {payload.fund_code} not found in funds table; "
                "create the fund record first (POST /api/funds) "
                "or run scripts/seed_funds.py"
            ),
        )
    # 唯一约束:同 fund 已持仓 → 409
    if db.scalar(select(Holding).where(Holding.fund_code == payload.fund_code)) is not None:
        raise HTTPException(
            status_code=409, detail=f"holding for {payload.fund_code} already exists"
        )

    h = Holding(
        fund_code=payload.fund_code,
        cost_nav_x10000=nav_to_int(payload.cost_nav),
        shares_x100=shares_to_int(payload.shares),
        bought_at=payload.bought_at,
        note=payload.note,
    )
    db.add(h)
    db.commit()
    db.refresh(h)
    return _to_response(h)


@router.put("/{fund_code}", response_model=HoldingResponse)
def update_holding(
    fund_code: str, payload: HoldingUpdate, db: Session = Depends(get_session)
):
    h = db.scalar(select(Holding).where(Holding.fund_code == fund_code))
    if h is None:
        raise HTTPException(status_code=404, detail=f"holding for {fund_code} not found")
    if payload.cost_nav is not None:
        h.cost_nav_x10000 = nav_to_int(payload.cost_nav)
    if payload.shares is not None:
        h.shares_x100 = shares_to_int(payload.shares)
    if payload.bought_at is not None:
        h.bought_at = payload.bought_at
    if payload.note is not None:
        h.note = payload.note
    db.commit()
    db.refresh(h)
    return _to_response(h)


@router.delete("/{fund_code}", status_code=status.HTTP_204_NO_CONTENT)
def delete_holding(fund_code: str, db: Session = Depends(get_session)):
    h = db.scalar(select(Holding).where(Holding.fund_code == fund_code))
    if h is None:
        raise HTTPException(status_code=404, detail=f"holding for {fund_code} not found")
    db.delete(h)
    db.commit()
