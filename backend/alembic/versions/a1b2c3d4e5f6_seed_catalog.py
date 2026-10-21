"""seed catalog data

Revision ID: a1b2c3d4e5f6
Revises: 052d98b6b87a
Create Date: 2026-10-21 19:40:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: str | Sequence[str] | None = '052d98b6b87a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Каталог моделей: slug -> (price, [(provider, priority, max_ref_images, skip_on_moderation)])
CATALOG: dict[str, tuple[int, list[tuple[str, int, int, bool]]]] = {
    'image-fast': (2, [('alpha', 0, 4, False), ('beta', 1, 10, False)]),
    'video-long': (25, [('beta', 0, 2, True), ('alpha', 1, 1, False)]),
}


def upgrade() -> None:
    """Заполнить каталог моделей и их ног."""
    connection = op.get_bind()

    models_table = sa.table(
        'models',
        sa.column('slug', sa.String),
        sa.column('price', sa.BigInteger),
        sa.column('created_at', sa.DateTime(timezone=True)),
    )
    legs_table = sa.table(
        'model_legs',
        sa.column('id', sa.Uuid()),
        sa.column('model_slug', sa.String),
        sa.column('provider', sa.Enum('alpha', 'beta', name='providerenum')),
        sa.column('priority', sa.Integer),
        sa.column('max_ref_images', sa.Integer),
        sa.column('skip_on_moderation', sa.Boolean),
        sa.column('created_at', sa.DateTime(timezone=True)),
    )

    import uuid
    from datetime import UTC, datetime

    now = datetime.now(UTC)

    for slug, (price, legs) in CATALOG.items():
        connection.execute(models_table.insert().values(slug=slug, price=price, created_at=now))
        for provider, priority, max_ref_images, skip_on_moderation in legs:
            connection.execute(
                legs_table.insert().values(
                    id=uuid.uuid4(),
                    model_slug=slug,
                    provider=provider,
                    priority=priority,
                    max_ref_images=max_ref_images,
                    skip_on_moderation=skip_on_moderation,
                    created_at=now,
                )
            )


def downgrade() -> None:
    """Удалить каталог моделей и их ног."""
    connection = op.get_bind()
    for slug in CATALOG:
        connection.execute(sa.text('DELETE FROM model_legs WHERE model_slug = :slug'), {'slug': slug})
        connection.execute(sa.text('DELETE FROM models WHERE slug = :slug'), {'slug': slug})
