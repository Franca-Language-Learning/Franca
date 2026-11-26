"""Sessions record the passkey they were started with, so that removing a passkey ends its sessions (story E02-003).

Revision ID: 0002
Revises: 0001
Created: 2026-11-26
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "ALTER TABLE identity_auth_session ADD COLUMN passkey_credential_id BLOB REFERENCES identity_passkey ON DELETE SET NULL"
    )
    connection.exec_driver_sql("CREATE INDEX identity_auth_session_passkey ON identity_auth_session (passkey_credential_id)")


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("DROP INDEX identity_auth_session_passkey")
    connection.exec_driver_sql("ALTER TABLE identity_auth_session DROP COLUMN passkey_credential_id")
