"""pytest 全局 fixture。

每个 test 拿一份独立的内存 SQLite(StaticPool 共享单连接,
避免 :memory: 每个连接独立 DB 的坑)+ dependency_overrides
切换 FastAPI app 用的 session。
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.db import Base, get_session
from src.main import app


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture
def db_session(db_engine) -> Generator[Session, None, None]:
    Maker = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    session = Maker()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_engine) -> Generator[TestClient, None, None]:
    Maker = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)

    def override_session():
        session = Maker()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
