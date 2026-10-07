"""Run MOSAIC migrations on an explicitly supplied database connection."""

from alembic import context
from sqlalchemy.engine import Connection


def run_migrations_online() -> None:
    """Run migrations using the connection owned by ``MosaicDatabase``.

    Raises:
        RuntimeError: If the migration runner did not supply a connection.
    """
    connection = context.config.attributes.get('connection')
    if not isinstance(connection, Connection):
        raise RuntimeError(
            'MOSAIC migrations require an owned database connection.'
        )

    context.configure(
        connection=connection,
        target_metadata=None,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError('Offline MOSAIC migrations are not supported.')
run_migrations_online()
