# -*- coding: utf-8 -*-
"""应用配置。OA SSO 参数预留，待厂商文档到位后填入。

v1.1 安全加固（2026-09-05 代码审查后）：
- secret_key 改为必填 env（缺失即启动失败），禁止默认值
- debug 由 env 控制，默认 False
- 新增 TEST_DATABASE_URL（测试库隔离）
- 新增 dev_token（开发期固定 token，fail-closed 鉴权用）
"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )
    # 数据库
    database_url: str = "postgresql+psycopg2://odoo@localhost:5432/zaojia_db"
    # 测试数据库（pytest 用，隔离开发/生产库；为 None 时回退 database_url）
    test_database_url: str | None = None

    # 应用
    app_name: str = "造价数据门户"
    # debug 由 env 控制，默认 False（禁止提交 True）
    debug: bool = False
    # 运行环境：development / production
    env: str = "development"

    # 安全密钥（必填，缺失即启动失败；禁止默认值 "change-me"）
    secret_key: str

    # 开发期固定 token（fail-closed 鉴权用；仅 env=development 时生效）
    # OA SSO 对接后此字段废弃，get_current_user 改为校验 OA token
    dev_token: str = ""

    # OA SSO（预留，待易达 ECMS 对接文档）
    oa_sso_enabled: bool = False
    oa_sso_client_id: str = ""
    oa_sso_client_secret: str = ""
    oa_sso_authorize_url: str = ""
    oa_sso_token_url: str = ""
    oa_sso_userinfo_url: str = ""


settings = Settings()
