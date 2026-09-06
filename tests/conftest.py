# -*- coding: utf-8 -*-
"""pytest 配置与共享 fixture。

测试隔离策略：
- 模块级 SQLite 内存库（StaticPool 保证 TestClient 后台线程共享同一连接）
- db_session：每个测试一个 session，测试结束 rollback + 清空表
- client：FastAPI TestClient，override get_db 指向测试会话
- app.state.db_session_factory：供 AuditMiddleware 使用测试库
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.db import Base, get_db
from app.main import app

# 导入所有模型，确保 Base.metadata 注册
from app.models import (  # noqa: F401
    boq_item, import_batch, material_dict, audit_log,
)
try:
    from app.models import cost_catalog  # noqa: F401
except ImportError:
    pass

# 模块级测试 engine 和 SessionLocal（所有测试共享同一内存库）
_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)
TestingSessionLocal = sessionmaker(
    bind=_test_engine, autoflush=False, expire_on_commit=False, future=True,
)
Base.metadata.create_all(bind=_test_engine)

# 供 AuditMiddleware 使用（中间件从 app.state 读取，避免直接 import 全局 SessionLocal）
app.state.db_session_factory = TestingSessionLocal


def _clear_all_tables():
    """清空所有表数据（不删表）。"""
    from app.models.base_mixin import Base
    with _test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture()
def db_session():
    """每个测试独立会话，测试结束 rollback + 清空表。"""
    _clear_all_tables()
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        _clear_all_tables()


@pytest.fixture()
def client(db_session):
    """FastAPI TestClient，get_db 依赖指向测试会话。"""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
