"""Persist compact workflow-run step and diagnostic summaries."""

from alembic import op


revision = "20260908_0003"
down_revision = "20260907_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE workflow_runs
            ADD COLUMN step_summaries jsonb NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN diagnostics jsonb NOT NULL DEFAULT '[]'::jsonb
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE workflow_runs
            DROP COLUMN diagnostics,
            DROP COLUMN step_summaries
        """
    )
