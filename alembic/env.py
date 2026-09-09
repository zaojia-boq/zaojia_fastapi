# -*- coding: utf-8 -*-
"""Alembic 环境配置。

从 app.config.settings 读取数据库 URL，不硬编码。
导入所有模型确保 Base.metadata 注册完整。
"""
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# 项目配置
from app.config import settings
from app.models.base_mixin import Base

# 导入所有模型，确保 Base.metadata 注册完整
from app.models import (  # noqa: F401
    boq_item, import_batch, material_dict, audit_log, match_cache,
)
try:
    from app.models import cost_catalog  # noqa: F401
except ImportError:
    pass
try:
    from app.models import favorite  # noqa: F401
except ImportError:
    pass
try:
    from app.models import tag  # noqa: F401
except ImportError:
    pass

# Alembic Config 对象
config = context.config

# 从项目 settings 读取数据库 URL（覆盖 alembic.ini 中的占位值）
config.set_main_option("sqlalchemy.url", settings.database_url)

# 配置日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 模型元数据（用于 autogenerate）
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：以 SQL 脚本形式输出迁移。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,  # 比较列类型变化
        compare_server_default=True,  # 比较默认值变化
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：直接在数据库上执行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,  # 比较列类型变化
            compare_server_default=True,  # 比较默认值变化
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
