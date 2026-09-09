"""Persist bounded provider usage metadata with agent executions."""

from alembic import op


revision = "20260909_0004"
down_revision = "20260908_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE execution_runs ADD COLUMN provider_usage jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE execution_runs DROP COLUMN provider_usage")
