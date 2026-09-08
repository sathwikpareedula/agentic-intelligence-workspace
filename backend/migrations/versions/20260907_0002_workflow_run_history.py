"""Add immutable workflow-run snapshots and comparison facts."""

from alembic import op


revision = "20260907_0002"
down_revision = "20260903_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE workflow_runs
            ADD COLUMN definition_fingerprint char(64),
            ADD COLUMN lifecycle jsonb NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN input_snapshots jsonb NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN facts jsonb NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN artifacts jsonb NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN drift_findings jsonb NOT NULL DEFAULT '[]'::jsonb
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE workflow_runs
            DROP COLUMN drift_findings,
            DROP COLUMN warnings,
            DROP COLUMN artifacts,
            DROP COLUMN facts,
            DROP COLUMN input_snapshots,
            DROP COLUMN lifecycle,
            DROP COLUMN definition_fingerprint
        """
    )
