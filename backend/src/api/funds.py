"""funds CRUD endpoints。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db import get_session
from src.models import Fund
from src.schemas.funds import FundCreate, FundResponse

router = APIRouter(prefix="/api/funds", tags=["funds"])


@router.get("", response_model=list[FundResponse])
def list_funds(db: Session = Depends(get_session)):
    return list(db.scalars(select(Fund).order_by(Fund.fund_code)))


@router.get("/{fund_code}", response_model=FundResponse)
def get_fund(fund_code: str, db: Session = Depends(get_session)):
    fund = db.get(Fund, fund_code)
    if fund is None:
        raise HTTPException(status_code=404, detail=f"fund {fund_code} not found")
    return fund


@router.post("", response_model=FundResponse, status_code=status.HTTP_201_CREATED)
def create_fund(payload: FundCreate, db: Session = Depends(get_session)):
    if db.get(Fund, payload.fund_code) is not None:
        raise HTTPException(
            status_code=409, detail=f"fund {payload.fund_code} already exists"
        )
    fund = Fund(**payload.model_dump())
    db.add(fund)
    db.commit()
    db.refresh(fund)
    return fund


@router.post(
    "/batch", response_model=list[FundResponse], status_code=status.HTTP_201_CREATED
)
def create_funds_batch(payload: list[FundCreate], db: Session = Depends(get_session)):
    """批量导入。已存在的 fund_code 跳过(幂等)。返回**新创建**的列表。"""
    created: list[Fund] = []
    for item in payload:
        if db.get(Fund, item.fund_code) is not None:
            continue
        fund = Fund(**item.model_dump())
        db.add(fund)
        created.append(fund)
    db.commit()
    for f in created:
        db.refresh(f)
    return created
