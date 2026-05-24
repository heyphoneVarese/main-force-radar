"""holdings API 的 Pydantic schema。

对外暴露 Decimal(用户面友好),内部走 money.py 转 int 存库(R1)。
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.utils.date_helper import cn_today
from src.utils.fund_code import is_valid_fund_code


class HoldingBase(BaseModel):
    fund_code: str = Field(description="6 位基金代码")
    cost_nav: Decimal = Field(gt=Decimal("0"), description="持仓成本净值,如 1.2345")
    shares: Decimal = Field(gt=Decimal("0"), description="持仓份额,如 1000.50")
    bought_at: date = Field(description="建仓日,不能晚于今天")
    note: str | None = Field(default=None, description="备注")

    @field_validator("fund_code")
    @classmethod
    def _validate_code(cls, v: str) -> str:
        if not is_valid_fund_code(v):
            raise ValueError(f"invalid fund_code: '{v}' (must be 6 digits)")
        return v

    @field_validator("bought_at")
    @classmethod
    def _validate_bought_at(cls, v: date) -> date:
        if v > cn_today():
            raise ValueError(f"bought_at {v} cannot be in the future")
        return v


class HoldingCreate(HoldingBase):
    pass


class HoldingUpdate(BaseModel):
    """PUT 部分更新。fund_code 不可改(改的话删了重建)。"""

    cost_nav: Decimal | None = Field(default=None, gt=Decimal("0"))
    shares: Decimal | None = Field(default=None, gt=Decimal("0"))
    bought_at: date | None = None
    note: str | None = None

    @field_validator("bought_at")
    @classmethod
    def _validate_bought_at(cls, v: date | None) -> date | None:
        if v is not None and v > cn_today():
            raise ValueError(f"bought_at {v} cannot be in the future")
        return v


class HoldingResponse(BaseModel):
    id: int
    fund_code: str
    cost_nav: Decimal
    shares: Decimal
    bought_at: date
    note: str | None
    created_at: datetime
    updated_at: datetime
