"""add material_dict parent_name composite index

Revision ID: a1b2c3d4e5f6
Revises: 8f01e7bf36ce
Create Date: 2026-09-14 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '8f01e7bf36ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # (parent_id, name) 复合索引：/dict/children 的 filter(parent_id==).order_by(name) 走此索引
    op.create_index(
        'ix_material_dict_parent_name',
        'material_dict',
        ['parent_id', 'name'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_material_dict_parent_name', table_name='material_dict')
