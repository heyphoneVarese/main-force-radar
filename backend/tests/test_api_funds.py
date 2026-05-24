def _payload(code="110011", name="易方达消费行业", ftype="混合型"):
    return {"fund_code": code, "fund_name": name, "fund_type": ftype}


# ============ POST 单条 ============


def test_post_fund_creates(client):
    resp = client.post("/api/funds", json=_payload())
    assert resp.status_code == 201
    data = resp.json()
    assert data["fund_code"] == "110011"
    assert data["fund_name"] == "易方达消费行业"


def test_post_fund_duplicate_returns_409(client):
    client.post("/api/funds", json=_payload())
    resp = client.post("/api/funds", json=_payload())
    assert resp.status_code == 409


def test_post_fund_invalid_code_format_returns_422(client):
    resp = client.post("/api/funds", json=_payload(code="abc"))
    assert resp.status_code == 422


def test_post_fund_with_related_sectors(client):
    payload = _payload(code="159995", name="国泰CES半导体ETF联接A", ftype="指数型")
    payload["related_sectors"] = ["BK0428", "BK0429"]
    resp = client.post("/api/funds", json=payload)
    assert resp.status_code == 201
    assert resp.json()["related_sectors"] == ["BK0428", "BK0429"]


# ============ GET 列表 / 单条 ============


def test_get_list_returns_all(client):
    client.post("/api/funds", json=_payload("110011", "A"))
    client.post("/api/funds", json=_payload("110012", "B"))
    resp = client.get("/api/funds")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_get_single_404_when_missing(client):
    resp = client.get("/api/funds/999999")
    assert resp.status_code == 404


# ============ POST 批量 ============


def test_post_batch_inserts_and_skips_duplicates(client):
    client.post("/api/funds", json=_payload("110011", "A"))
    batch = [
        _payload("110011", "A-dup"),  # 已存在,跳过
        _payload("110012", "B"),
        _payload("110013", "C"),
    ]
    resp = client.post("/api/funds/batch", json=batch)
    assert resp.status_code == 201
    created = resp.json()
    assert len(created) == 2
    assert {f["fund_code"] for f in created} == {"110012", "110013"}
    # 总列表 3 条(原 1 + 新 2)
    assert len(client.get("/api/funds").json()) == 3
