"""funds API 的 Pydantic schema。"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.utils.fund_code import is_valid_fund_code


class FundBase(BaseModel):
    fund_code: str = Field(description="6 位基金代码")
    fund_name: str = Field(min_length=1, max_length=100)
    fund_type: str = Field(
        min_length=1, max_length=20, description="如:混合型 / 指数型 / QDII"
    )
    company: str | None = Field(default=None, max_length=100)
    manager: str | None = Field(default=None, max_length=50)
    establish_date: date | None = None
    tracking_target: str | None = Field(default=None, max_length=100)
    related_sectors: list[str] | None = Field(
        default=None, description="关注板块代码列表,如 ['BK0428']"
    )

    @field_validator("fund_code")
    @classmethod
    def _validate_code(cls, v: str) -> str:
        if not is_valid_fund_code(v):
            raise ValueError(f"invalid fund_code: '{v}' (must be 6 digits)")
        return v


class FundCreate(FundBase):
    pass


class FundResponse(FundBase):
    model_config = ConfigDict(from_attributes=True)

    created_at: datetime
    updated_at: datetime
