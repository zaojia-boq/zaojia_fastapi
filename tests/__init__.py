# -*- coding: utf-8 -*-
"""集成测试包（tests/）。

测试范围：
- test_models.py：SQLAlchemy 四模型验证（创建/查询/约束/关系/append-only）
- test_security.py：S1–S9 安全用例（对照 docs/reference/security_test_spec.md，M1.5 实现）
- test_api.py：FastAPI 路由集成测试（M2 实现）

测试库：默认 SQLite 内存库（不碰 PostgreSQL），通过 conftest.py override get_db。
如需用真实 PostgreSQL 测试，设置环境变量 TEST_DATABASE_URL。
"""
