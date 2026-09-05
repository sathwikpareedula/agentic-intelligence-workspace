"""Create durable workflow, artifact, execution, and pgvector retrieval storage."""

from alembic import op


revision = "20260903_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE documents (
            id uuid PRIMARY KEY,
            filename text NOT NULL CHECK (filename <> ''),
            page_count integer NOT NULL CHECK (page_count > 0),
            embedding_provider text NOT NULL CHECK (embedding_provider <> ''),
            embedding_model text NOT NULL CHECK (embedding_model <> ''),
            embedding_dimensions integer NOT NULL CHECK (embedding_dimensions > 0 AND embedding_dimensions <= 16000),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE document_chunks (
            id uuid PRIMARY KEY,
            document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            page_number integer NOT NULL CHECK (page_number > 0),
            chunk_index integer NOT NULL CHECK (chunk_index >= 0),
            content text NOT NULL CHECK (content <> ''),
            embedding vector NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (document_id, page_number, chunk_index)
        )
        """
    )
    op.execute("CREATE INDEX document_chunks_document_id_idx ON document_chunks (document_id)")
    op.execute(
        """
        CREATE TABLE workflows (
            id uuid PRIMARY KEY,
            name text NOT NULL CHECK (name <> ''),
            source_task_id uuid,
            current_version integer NOT NULL CHECK (current_version > 0),
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE workflow_versions (
            workflow_id uuid NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
            version integer NOT NULL CHECK (version > 0),
            recipe jsonb NOT NULL,
            created_at timestamptz NOT NULL,
            PRIMARY KEY (workflow_id, version)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE workflow_runs (
            id uuid PRIMARY KEY,
            workflow_id uuid NOT NULL,
            workflow_version integer NOT NULL,
            status text NOT NULL CHECK (status IN ('completed', 'failed')),
            started_at timestamptz NOT NULL,
            completed_at timestamptz NOT NULL,
            step_overrides jsonb NOT NULL DEFAULT '{}'::jsonb,
            observations jsonb NOT NULL DEFAULT '[]'::jsonb,
            failed_step integer,
            error text,
            artifact_ids uuid[] NOT NULL DEFAULT '{}'::uuid[],
            verification jsonb,
            FOREIGN KEY (workflow_id, workflow_version)
                REFERENCES workflow_versions(workflow_id, version) ON DELETE RESTRICT
        )
        """
    )
    op.execute("CREATE INDEX workflow_runs_workflow_id_idx ON workflow_runs (workflow_id, started_at DESC)")
    op.execute(
        """
        CREATE TABLE artifacts (
            id uuid PRIMARY KEY,
            filename text NOT NULL CHECK (filename <> ''),
            artifact_type text NOT NULL CHECK (artifact_type <> ''),
            media_type text NOT NULL CHECK (media_type <> ''),
            row_count integer NOT NULL CHECK (row_count >= 0),
            column_count integer NOT NULL CHECK (column_count >= 0),
            storage_key text NOT NULL UNIQUE CHECK (storage_key <> ''),
            size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
            content_sha256 char(64) NOT NULL,
            producing_task_id uuid,
            producing_workflow_id uuid REFERENCES workflows(id) ON DELETE SET NULL,
            producing_run_id uuid,
            verification_status text NOT NULL DEFAULT 'not_verified'
                CHECK (verification_status IN ('not_verified', 'verified', 'failed')),
            provenance jsonb,
            created_at timestamptz NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX artifacts_producing_task_id_idx ON artifacts (producing_task_id)")
    op.execute(
        """
        CREATE TABLE execution_runs (
            id uuid PRIMARY KEY,
            user_goal text NOT NULL CHECK (user_goal <> ''),
            status text NOT NULL CHECK (status IN ('completed', 'failed', 'iteration_limit')),
            started_at timestamptz NOT NULL,
            completed_at timestamptz NOT NULL,
            tool_trace jsonb NOT NULL DEFAULT '[]'::jsonb,
            artifact_ids uuid[] NOT NULL DEFAULT '{}'::uuid[],
            verification jsonb,
            failure_reason text
        )
        """
    )
    op.execute("CREATE INDEX execution_runs_started_at_idx ON execution_runs (started_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE execution_runs")
    op.execute("DROP TABLE artifacts")
    op.execute("DROP TABLE workflow_runs")
    op.execute("DROP TABLE workflow_versions")
    op.execute("DROP TABLE workflows")
    op.execute("DROP TABLE document_chunks")
    op.execute("DROP TABLE documents")
