import json
import unittest
from io import StringIO
from unittest.mock import Mock, patch

from mosaic.components.identity.mosaic_admin_cli import MosaicAdminCli


class TestMosaicAdminCli(unittest.TestCase):
    @patch('mosaic.components.identity.mosaic_admin_cli.HTTPSConnection')
    def test_create_user_prints_one_time_response(
        self,
        connection_type: Mock,
    ) -> None:
        connection = connection_type.return_value
        response = connection.getresponse.return_value
        response.status = 201
        response.read.return_value = json.dumps(
            {
                'user_id': 'pilot-user',
                'plaintext_token': 'mosaic_r1_synthetic-token',
            }
        ).encode('utf-8')
        output = StringIO()

        with (
            patch.dict(
                'os.environ',
                {'MOSAIC_PILOT_ADMIN_SECRET': 'a' * 32},
                clear=True,
            ),
            patch('sys.stdout', output),
        ):
            exit_status = MosaicAdminCli.run(
                [
                    '--api-url',
                    'https://mosaic.example.com',
                    'create-user',
                    'pilot-user',
                ]
            )

        self.assertEqual(exit_status, 0)
        connection.request.assert_called_once_with(
            'POST',
            '/api/v1/admin/users',
            body=b'{"user_id": "pilot-user"}',
            headers={
                'Accept': 'application/json',
                'Authorization': f'Bearer {"a" * 32}',
                'Content-Type': 'application/json',
            },
        )
        self.assertIn('mosaic_r1_synthetic-token', output.getvalue())
        connection.close.assert_called_once_with()

    @patch('mosaic.components.identity.mosaic_admin_cli.HTTPSConnection')
    def test_list_users_reads_api_url_from_environment(
        self,
        connection_type: Mock,
    ) -> None:
        connection = connection_type.return_value
        response = connection.getresponse.return_value
        response.status = 200
        response.read.return_value = b'[]'
        output = StringIO()

        with (
            patch.dict(
                'os.environ',
                {
                    'MOSAIC_API_URL': 'https://mosaic.example.com/base',
                    'MOSAIC_PILOT_ADMIN_SECRET': 'a' * 32,
                },
                clear=True,
            ),
            patch('sys.stdout', output),
        ):
            exit_status = MosaicAdminCli.run(['list-users'])

        self.assertEqual(exit_status, 0)
        connection.request.assert_called_once_with(
            'GET',
            '/base/api/v1/admin/users',
            body=None,
            headers={
                'Accept': 'application/json',
                'Authorization': f'Bearer {"a" * 32}',
            },
        )
        self.assertEqual(json.loads(output.getvalue()), [])

    @patch('mosaic.components.identity.mosaic_admin_cli.HTTPSConnection')
    def test_disable_user_reports_empty_success(
        self,
        connection_type: Mock,
    ) -> None:
        response = connection_type.return_value.getresponse.return_value
        response.status = 204
        output = StringIO()

        with (
            patch.dict(
                'os.environ',
                {'MOSAIC_PILOT_ADMIN_SECRET': 'a' * 32},
                clear=True,
            ),
            patch('sys.stdout', output),
        ):
            exit_status = MosaicAdminCli.run(
                [
                    '--api-url',
                    'https://mosaic.example.com',
                    'disable-user',
                    'pilot-user',
                ]
            )

        self.assertEqual(exit_status, 0)
        self.assertEqual(output.getvalue(), 'User disabled.\n')

    @patch('mosaic.components.identity.mosaic_admin_cli.HTTPSConnection')
    def test_failure_does_not_print_response_body(
        self,
        connection_type: Mock,
    ) -> None:
        response = connection_type.return_value.getresponse.return_value
        response.status = 403
        response.read.return_value = b'sensitive response body'
        error_output = StringIO()

        with (
            patch.dict(
                'os.environ',
                {'MOSAIC_PILOT_ADMIN_SECRET': 'a' * 32},
                clear=True,
            ),
            patch('sys.stderr', error_output),
        ):
            exit_status = MosaicAdminCli.run(
                [
                    '--api-url',
                    'https://mosaic.example.com',
                    'list-users',
                ]
            )

        self.assertEqual(exit_status, 2)
        self.assertEqual(
            error_output.getvalue(),
            'Administration request failed with HTTP 403.\n',
        )
        self.assertNotIn('sensitive', error_output.getvalue())

    def test_non_loopback_http_url_is_rejected(self) -> None:
        error_output = StringIO()

        with (
            patch.dict(
                'os.environ',
                {'MOSAIC_PILOT_ADMIN_SECRET': 'a' * 32},
                clear=True,
            ),
            patch('sys.stderr', error_output),
        ):
            exit_status = MosaicAdminCli.run(
                [
                    '--api-url',
                    'http://mosaic.example.com',
                    'list-users',
                ]
            )

        self.assertEqual(exit_status, 2)
        self.assertEqual(
            error_output.getvalue(),
            'MOSAIC API URL must use HTTPS except on loopback.\n',
        )

    def test_missing_secret_is_rejected_before_network_access(self) -> None:
        error_output = StringIO()

        with (
            patch.dict('os.environ', {}, clear=True),
            patch('sys.stderr', error_output),
        ):
            exit_status = MosaicAdminCli.run(
                [
                    '--api-url',
                    'https://mosaic.example.com',
                    'list-users',
                ]
            )

        self.assertEqual(exit_status, 2)
        self.assertEqual(
            error_output.getvalue(),
            'MOSAIC_PILOT_ADMIN_SECRET is required.\n',
        )

    @patch('mosaic.components.identity.mosaic_admin_cli.HTTPSConnection')
    def test_show_workspace_skills_calls_protected_endpoint(
        self,
        connection_type: Mock,
    ) -> None:
        connection = connection_type.return_value
        response = connection.getresponse.return_value
        response.status = 200
        response.read.return_value = b'{"skill_ids": []}'
        output = StringIO()

        with (
            patch.dict(
                'os.environ',
                {'MOSAIC_PILOT_ADMIN_SECRET': 'a' * 32},
                clear=True,
            ),
            patch('sys.stdout', output),
        ):
            exit_status = MosaicAdminCli.run(
                [
                    '--api-url',
                    'https://mosaic.example.com',
                    'workspaces',
                    'show-skills',
                    'pilot-user',
                ]
            )

        self.assertEqual(exit_status, 0)
        self.assertEqual(
            connection.request.call_args.args[:2],
            (
                'GET',
                '/api/v1/admin/workspaces/pilot-user/skills',
            ),
        )

    @patch('mosaic.components.identity.mosaic_admin_cli.HTTPSConnection')
    def test_set_workspace_skills_sends_repeated_selections(
        self,
        connection_type: Mock,
    ) -> None:
        connection = connection_type.return_value
        response = connection.getresponse.return_value
        response.status = 200
        response.read.return_value = b'{"applied": false}'
        output = StringIO()

        with (
            patch.dict(
                'os.environ',
                {'MOSAIC_PILOT_ADMIN_SECRET': 'a' * 32},
                clear=True,
            ),
            patch('sys.stdout', output),
        ):
            exit_status = MosaicAdminCli.run(
                [
                    '--api-url',
                    'https://mosaic.example.com',
                    'workspaces',
                    'set-skills',
                    'pilot-user',
                    '--skill',
                    'inspect-platform',
                    '--skill',
                    'summarize-findings',
                    '--group',
                    'platform/diagnostics',
                    '--dry-run',
                ]
            )

        self.assertEqual(exit_status, 0)
        request_call = connection.request.call_args
        self.assertEqual(request_call.args[0], 'PUT')
        self.assertEqual(
            request_call.args[1],
            '/api/v1/admin/workspaces/pilot-user/skills',
        )
        self.assertEqual(
            json.loads(request_call.kwargs['body']),
            {
                'skill_ids': [
                    'inspect-platform',
                    'summarize-findings',
                ],
                'group_ids': ['platform/diagnostics'],
                'clear': False,
                'dry_run': True,
            },
        )

    @patch('mosaic.components.identity.mosaic_admin_cli.HTTPSConnection')
    def test_set_workspace_skills_requires_explicit_clear(
        self,
        connection_type: Mock,
    ) -> None:
        error_output = StringIO()

        with (
            patch.dict(
                'os.environ',
                {'MOSAIC_PILOT_ADMIN_SECRET': 'a' * 32},
                clear=True,
            ),
            patch('sys.stderr', error_output),
        ):
            exit_status = MosaicAdminCli.run(
                [
                    '--api-url',
                    'https://mosaic.example.com',
                    'workspaces',
                    'set-skills',
                    'pilot-user',
                ]
            )

        self.assertEqual(exit_status, 2)
        self.assertEqual(
            error_output.getvalue(),
            '--clear is required for an empty Skill set.\n',
        )
        connection_type.assert_not_called()
