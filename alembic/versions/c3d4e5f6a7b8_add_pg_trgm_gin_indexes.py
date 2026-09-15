"""add pg_trgm extension + GIN indexes for boq_item search

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-15 14:35:00.000000

启用 pg_trgm 扩展 + 两个 GIN 索引，把模糊匹配从 Python 端 rapidfuzz 全表扫描
下沉到 PostgreSQL 数据库层。百万级数据量搜索仍可保持 20-50ms。

边界规则（在 app/services/page_services.py 中实现）：
- 仅单字词（空格拆分后只有一个词）且长度≥2且非纯数字时触发相似度模糊匹配
- 多词 AND 搜索不触发模糊兜底（避免"20"这类短数字词误匹配）
- 阈值 similarity() > 0.3（中文材料名场景）
- 名称命中权重高于特征命中

索引维护：
- 批量导入数据后再建索引（当前已建）
- 定期 VACUUM ANALYZE boq_item;
- postgresql.conf 调优：gin_pending_list_limit=64MB, maintenance_work_mem=256MB
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 启用 pg_trgm 扩展（三元组分词，支持 ILIKE '%xxx%' 和 similarity()）
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # GIN 索引：boq_item.item_name（项目名称，权重最高）
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_boq_item_name_trgm "
        "ON boq_item USING gin (item_name gin_trgm_ops)"
    )

    # GIN 索引：boq_item.item_feature（项目特征/规格描述）
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_boq_item_feature_trgm "
        "ON boq_item USING gin (item_feature gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_boq_item_feature_trgm")
    op.execute("DROP INDEX IF EXISTS idx_boq_item_name_trgm")
    # 注意：不 DROP EXTENSION，因为其他扩展可能依赖 pg_trgm
