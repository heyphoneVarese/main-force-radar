from datetime import date, timedelta

from src.models import Fund


def _ensure_fund(db_session, code="110011", name="测试基金", ftype="混合型"):
    db_session.add(Fund(fund_code=code, fund_name=name, fund_type=ftype))
    db_session.commit()


def _payload(code="110011"):
    return {
        "fund_code": code,
        "cost_nav": "1.2345",
        "shares": "1000.50",
        "bought_at": "2026-05-01",
        "note": "test holding",
    }


# ============ POST 正常路径 ============


def test_post_holding_with_existing_fund(client, db_session):
    _ensure_fund(db_session)
    resp = client.post("/api/holdings", json=_payload())
    assert resp.status_code == 201
    data = resp.json()
    assert data["fund_code"] == "110011"
    # R1 闭环:Decimal in → int 存 → Decimal out
    assert data["cost_nav"] == "1.2345"
    # Decimal 除法会去掉尾随 0
    assert data["shares"] == "1000.5"
    assert data["bought_at"] == "2026-05-01"
    assert data["note"] == "test holding"


# ============ POST 异常路径 ============


def test_post_holding_fund_not_exist_returns_400(client):
    """fund 不在 funds 表 → 400 (per user 强校验 决策)。"""
    resp = client.post("/api/holdings", json=_payload(code="999999"))
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "999999" in detail
    assert "/api/funds" in detail  # 错误信息引导用户去 POST /api/funds


def test_post_holding_invalid_code_format_returns_422(client):
    resp = client.post("/api/holdings", json=_payload(code="abc"))
    assert resp.status_code == 422


def test_post_holding_negative_cost_nav_returns_422(client, db_session):
    _ensure_fund(db_session)
    payload = _payload()
    payload["cost_nav"] = "-1.0"
    resp = client.post("/api/holdings", json=payload)
    assert resp.status_code == 422


def test_post_holding_zero_shares_returns_422(client, db_session):
    _ensure_fund(db_session)
    payload = _payload()
    payload["shares"] = "0"
    resp = client.post("/api/holdings", json=payload)
    assert resp.status_code == 422


def test_post_holding_bought_at_future_returns_422(client, db_session):
    _ensure_fund(db_session)
    payload = _payload()
    payload["bought_at"] = str(date.today() + timedelta(days=1))
    resp = client.post("/api/holdings", json=payload)
    assert resp.status_code == 422


def test_post_holding_duplicate_returns_409(client, db_session):
    _ensure_fund(db_session)
    client.post("/api/holdings", json=_payload())
    resp = client.post("/api/holdings", json=_payload())
    assert resp.status_code == 409


# ============ GET ============


def test_get_list_returns_all(client, db_session):
    _ensure_fund(db_session, "110011")
    _ensure_fund(db_session, "110012")
    client.post("/api/holdings", json=_payload("110011"))
    client.post("/api/holdings", json=_payload("110012"))
    resp = client.get("/api/holdings")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_get_single_404_when_missing(client):
    resp = client.get("/api/holdings/999999")
    assert resp.status_code == 404


# ============ PUT ============


def test_put_updates_partial_fields(client, db_session):
    _ensure_fund(db_session)
    client.post("/api/holdings", json=_payload())
    resp = client.put(
        "/api/holdings/110011",
        json={"cost_nav": "1.5000", "note": "updated"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["cost_nav"] == "1.5"
    assert data["note"] == "updated"
    # 未传字段保持原值
    assert data["shares"] == "1000.5"
    assert data["bought_at"] == "2026-05-01"


def test_put_missing_returns_404(client):
    resp = client.put("/api/holdings/999999", json={"note": "x"})
    assert resp.status_code == 404


# ============ DELETE ============


def test_delete_removes_holding(client, db_session):
    _ensure_fund(db_session)
    client.post("/api/holdings", json=_payload())
    resp = client.delete("/api/holdings/110011")
    assert resp.status_code == 204
    assert client.get("/api/holdings/110011").status_code == 404


def test_delete_missing_returns_404(client):
    resp = client.delete("/api/holdings/999999")
    assert resp.status_code == 404
