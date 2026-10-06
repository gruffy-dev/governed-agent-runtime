"""Mock read-only database runbook retrieval tools."""

from pydantic import BaseModel, ConfigDict


class MockDatabaseRunbookMcpTools(BaseModel):
    """Return deterministic governed runbook evidence without external calls."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    def search_runbooks(self, query: str) -> dict[str, object]:
        """Search deterministic approved database runbook metadata.

        Args:
            query: Natural-language database task or support request.

        Returns:
            Ranked mock runbook candidates, or an ``invalid_request`` result
            for an empty query. This mock performs no external call.
        """
        if not query.strip():
            return {
                'status': 'invalid_request',
                'error': 'The database runbook query must not be empty.',
            }

        return {
            'status': 'success',
            'source': 'mock-database-runbook-mcp',
            'query': query.strip(),
            'candidates': [
                {
                    'runbook_id': 'DB-RB-0042',
                    'title': 'Restore PostgreSQL from an approved backup',
                    'version': '3.1.0',
                    'lifecycle_status': 'active',
                    'approval_status': 'approved',
                    'relevance_score': 0.94,
                    'matching_scope': 'PostgreSQL backup restoration',
                },
                {
                    'runbook_id': 'DB-RB-0017',
                    'title': 'Recover a PostgreSQL read replica',
                    'version': '2.4.0',
                    'lifecycle_status': 'active',
                    'approval_status': 'approved',
                    'relevance_score': 0.61,
                    'matching_scope': 'PostgreSQL replica recovery',
                },
            ],
        }

    def read_runbook(
        self,
        runbook_id: str,
        version: str,
    ) -> dict[str, object]:
        """Read one exact deterministic approved database runbook.

        Args:
            runbook_id: Stable identifier selected from search evidence.
            version: Exact immutable runbook version selected from evidence.

        Returns:
            Governed mock runbook content, or a ``not_found`` result when the
            requested identity does not match the deterministic fixture. This
            mock performs no external call and executes no runbook steps.
        """
        if runbook_id != 'DB-RB-0042' or version != '3.1.0':
            return {
                'status': 'not_found',
                'runbook_id': runbook_id,
                'version': version,
            }

        return {
            'status': 'success',
            'source': 'mock-database-runbook-mcp',
            'runbook': {
                'runbook_id': runbook_id,
                'title': 'Restore PostgreSQL from an approved backup',
                'version': version,
                'lifecycle_status': 'active',
                'approval_status': 'approved',
                'outcome': (
                    'Restore the selected PostgreSQL database from a '
                    'validated approved backup.'
                ),
                'prerequisites': [
                    'Confirmed database identity and target environment',
                    'Approved recovery point and validated backup',
                    'Recorded change and recovery authorisation',
                ],
                'warnings': [
                    'The restore is service-affecting.',
                    'This retrieval does not authorise or execute a restore.',
                ],
            },
        }
