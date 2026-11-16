"""add_fts5_virtual_tables

Revision ID: 32af45d4996c
Revises: 3a113ecd7b4d
Create Date: 2026-11-16 08:51:20.291153

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '32af45d4996c'
down_revision: Union[str, Sequence[str], None] = '3a113ecd7b4d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - Create FTS5 virtual tables (Section 7.1)."""
    op.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
            content_norm,
            sender_norm,
            title_norm,
            content='',
            contentless_delete=1,
            tokenize='unicode61 remove_diacritics 2'
        );
        """
    )
    op.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
            content_norm,
            content='',
            contentless_delete=1,
            tokenize='unicode61 remove_diacritics 2'
        );
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE IF EXISTS events_fts;")
    op.execute("DROP TABLE IF EXISTS memories_fts;")
