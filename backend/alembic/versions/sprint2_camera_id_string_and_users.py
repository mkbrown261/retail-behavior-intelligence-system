"""Sprint 2: camera_id Integer→String across 3 tables + users table

Revision ID: a1b2c3d4e5f6
Revises: 778249288549
Create Date: 2026-06-30 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '778249288549'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. alerts.camera_id  Integer → String ────────────────────────────────
    with op.batch_alter_table('alerts', schema=None) as batch_op:
        batch_op.alter_column(
            'camera_id',
            existing_type=sa.Integer(),
            type_=sa.String(),
            existing_nullable=True,
        )

    # ── 2. heatmap_points.camera_id  Integer → String ────────────────────────
    with op.batch_alter_table('heatmap_points', schema=None) as batch_op:
        batch_op.alter_column(
            'camera_id',
            existing_type=sa.Integer(),
            type_=sa.String(),
            existing_nullable=False,
        )

    # ── 3. suspicion_scores.camera_id  Integer → String ──────────────────────
    with op.batch_alter_table('suspicion_scores', schema=None) as batch_op:
        batch_op.alter_column(
            'camera_id',
            existing_type=sa.Integer(),
            type_=sa.String(),
            existing_nullable=True,
        )

    # ── 4. users table ────────────────────────────────────────────────────────
    op.create_table(
        'users',
        sa.Column('id',              sa.String(),    nullable=False),
        sa.Column('username',        sa.String(64),  nullable=False),
        sa.Column('email',           sa.String(255), nullable=True),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('role',            sa.String(32),  nullable=False),
        sa.Column('is_active',       sa.Boolean(),   nullable=False),
        sa.Column('is_verified',     sa.Boolean(),   nullable=False),
        sa.Column('created_at',  sa.DateTime(timezone=True),
                  server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('updated_at',  sa.DateTime(timezone=True),
                  server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('last_login',  sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_username'), ['username'], unique=True)
        batch_op.create_index(batch_op.f('ix_users_email'),    ['email'],    unique=True)


def downgrade() -> None:
    # Drop users table
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_email'))
        batch_op.drop_index(batch_op.f('ix_users_username'))
    op.drop_table('users')

    # Revert suspicion_scores.camera_id String → Integer
    with op.batch_alter_table('suspicion_scores', schema=None) as batch_op:
        batch_op.alter_column(
            'camera_id',
            existing_type=sa.String(),
            type_=sa.Integer(),
            existing_nullable=True,
        )

    # Revert heatmap_points.camera_id String → Integer
    with op.batch_alter_table('heatmap_points', schema=None) as batch_op:
        batch_op.alter_column(
            'camera_id',
            existing_type=sa.String(),
            type_=sa.Integer(),
            existing_nullable=False,
        )

    # Revert alerts.camera_id String → Integer
    with op.batch_alter_table('alerts', schema=None) as batch_op:
        batch_op.alter_column(
            'camera_id',
            existing_type=sa.String(),
            type_=sa.Integer(),
            existing_nullable=True,
        )
