"""add list_material_mapping table (M6 回归 Alembic 单轨)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-14 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 清单项目-材料字典映射表（支持2013/2024双版本）
    # 此前靠 scripts/force_create_table.py 的 DROP CASCADE 重建，现回归 Alembic 单轨
    op.create_table(
        'list_material_mapping',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('biz_id', sa.String(length=32), nullable=True, comment='业务ID（UUID，对外暴露）'),
        sa.Column('list_version', sa.String(length=8), nullable=False, server_default='2024', comment='清单规范版本（2013 / 2024）'),
        sa.Column('list_item_code', sa.String(length=32), nullable=False, comment='清单项目编码（9位）'),
        sa.Column('list_item_name', sa.String(), nullable=False, comment='清单项目名称'),
        sa.Column('material_code', sa.String(length=32), nullable=False, comment='材料字典编码（中建材料字典，15位含前缀I）'),
        sa.Column('material_name', sa.String(), nullable=False, comment='材料名称'),
        sa.Column('match_type', sa.String(length=32), nullable=False, comment='匹配类型（exact_name精确/fuzzy_name模糊/feature_match项目特征匹配）'),
        sa.Column('similarity', sa.Float(), nullable=False, server_default='0.0', comment='相似度（0-100）'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='更新时间'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('biz_id', name='list_material_mapping_biz_id_key'),
    )
    op.create_index(op.f('ix_list_material_mapping_list_item_code'), 'list_material_mapping', ['list_item_code'], unique=False)
    op.create_index(op.f('ix_list_material_mapping_list_item_name'), 'list_material_mapping', ['list_item_name'], unique=False)
    op.create_index(op.f('ix_list_material_mapping_list_version'), 'list_material_mapping', ['list_version'], unique=False)
    op.create_index(op.f('ix_list_material_mapping_material_code'), 'list_material_mapping', ['material_code'], unique=False)
    op.create_index(op.f('ix_list_material_mapping_material_name'), 'list_material_mapping', ['material_name'], unique=False)
    op.create_index('ix_list_material_mapping_version_code', 'list_material_mapping', ['list_version', 'list_item_code'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_list_material_mapping_version_code', table_name='list_material_mapping')
    op.drop_index(op.f('ix_list_material_mapping_material_name'), table_name='list_material_mapping')
    op.drop_index(op.f('ix_list_material_mapping_material_code'), table_name='list_material_mapping')
    op.drop_index(op.f('ix_list_material_mapping_list_version'), table_name='list_material_mapping')
    op.drop_index(op.f('ix_list_material_mapping_list_item_name'), table_name='list_material_mapping')
    op.drop_index(op.f('ix_list_material_mapping_list_item_code'), table_name='list_material_mapping')
    op.drop_table('list_material_mapping')
