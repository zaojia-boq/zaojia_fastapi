# -*- coding: utf-8 -*-
"""数据库引擎与会话管理。

v1.0（2026-09-05）：M1.1 地基三件套之一。
- engine：从 settings.database_url 创建
- SessionLocal：sessionmaker
- Base：从 app.models.base_mixin 导入（统一 metadata，避免双 Base 问题）
- get_db：FastAPI 依赖，yield session，自动关闭
- 测试时通过 TEST_DATABASE_URL 环境变量切换到测试库

设计原则：
- 引擎层与业务逻辑分离，models/ 只引用 Base，不直接操作 engine
- 测试库隔离：conftest.py 中 override get_db，用测试库 + create_all + 清空
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.base_mixin import Base  # 统一 Base，共享 metadata

# 数据库 URL：直接用生产/开发库；测试隔离由 conftest.py 的 dependency_overrides 完成
_db_url = settings.database_url

engine = create_engine(
    _db_url,
    echo=settings.debug,  # debug 模式打印 SQL
    pool_pre_ping=True,   # 连接池自动检测失效连接
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
    future=True,
)


def get_db():
    """FastAPI 依赖：获取数据库会话。

    用法：
        @app.get("/items")
        def list_items(db: Session = Depends(get_db)):
            ...

    测试时在 conftest.py 中 override：
        app.dependency_overrides[get_db] = override_get_db
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """创建所有表（开发期用，生产期用 Alembic 迁移）。

    调用：from app.db import init_db; init_db()
    """
    # 导入所有模型以确保 Base.metadata 注册
    from app.models import boq_item, import_batch, material_dict, audit_log  # noqa: F401
    try:
        from app.models import cost_catalog  # noqa: F401
    except ImportError:
        pass
    Base.metadata.create_all(bind=engine)
