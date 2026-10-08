import argparse
import json
import os
import sys
from http.client import HTTPConnection, HTTPSConnection
from typing import Any
from urllib.parse import SplitResult, quote, urlsplit


class MosaicAdminCli:
    @staticmethod
    def run(arguments: list[str] | None = None) -> int:
        """
        Execute one temporary pilot administration command.

        :param arguments: Optional command arguments excluding the executable.

        :return: Process exit status suitable for a console entry point.
        """
        parser = MosaicAdminCli._create_parser()
        parsed_arguments = parser.parse_args(arguments)
        api_url = parsed_arguments.api_url or os.getenv('MOSAIC_API_URL')
        administrator_secret = os.getenv('MOSAIC_PILOT_ADMIN_SECRET')
        if not api_url:
            print(
                'MOSAIC_API_URL or --api-url is required.',
                file=sys.stderr,
            )
            return 2
        if not administrator_secret:
            print(
                'MOSAIC_PILOT_ADMIN_SECRET is required.',
                file=sys.stderr,
            )
            return 2

        try:
            response = MosaicAdminCli._execute_command(
                api_url,
                administrator_secret,
                parsed_arguments,
            )
        except (TypeError, ValueError) as error:
            print(str(error), file=sys.stderr)
            return 2
        except OSError:
            print('Unable to reach the MOSAIC backend.', file=sys.stderr)
            return 1

        if response is None:
            print('User disabled.')
        else:
            print(json.dumps(response, indent=2, sort_keys=True))
        return 0

    @staticmethod
    def _create_parser() -> argparse.ArgumentParser:
        """
        Create the bounded pilot administration command parser.

        :return: Parser for supported administrator commands.
        """
        parser = argparse.ArgumentParser(prog='mosaic-admin')
        parser.add_argument(
            '--api-url',
            help='MOSAIC backend base URL; defaults to MOSAIC_API_URL.',
        )
        commands = parser.add_subparsers(dest='command', required=True)

        create_user = commands.add_parser(
            'create-user',
            help='Create one pilot user and print its token once.',
        )
        create_user.add_argument('user_id')

        commands.add_parser(
            'list-users',
            help='List pilot users without token material.',
        )

        disable_user = commands.add_parser(
            'disable-user',
            help='Disable one pilot user and its access tokens.',
        )
        disable_user.add_argument('user_id')
        return parser

    @staticmethod
    def _execute_command(
        api_url: str,
        administrator_secret: str,
        parsed_arguments: argparse.Namespace,
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """
        Map one parsed command to the protected administration API.

        :param api_url: Validated backend base URL supplied by the operator.
        :param administrator_secret: Dedicated pilot administrator secret.
        :param parsed_arguments: Parsed command name and arguments.

        :return: Decoded response or ``None`` for an empty success.

        :raises TypeError: If the server response has an invalid JSON type.
        :raises ValueError: If the command or server response is invalid.
        :raises OSError: If the backend cannot be reached.
        """
        if parsed_arguments.command == 'create-user':
            return MosaicAdminCli._send_request(
                api_url,
                administrator_secret,
                'POST',
                '/api/v1/admin/users',
                {'user_id': parsed_arguments.user_id},
            )
        if parsed_arguments.command == 'list-users':
            return MosaicAdminCli._send_request(
                api_url,
                administrator_secret,
                'GET',
                '/api/v1/admin/users',
                None,
            )
        if parsed_arguments.command == 'disable-user':
            return MosaicAdminCli._send_request(
                api_url,
                administrator_secret,
                'POST',
                '/api/v1/admin/users/'
                f'{quote(parsed_arguments.user_id, safe="")}/disable',
                None,
            )
        raise ValueError('Unsupported administrator command.')

    @staticmethod
    def _send_request(
        api_url: str,
        administrator_secret: str,
        method: str,
        endpoint_path: str,
        request_body: dict[str, Any] | None,
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """
        Send one non-redirecting request to the protected backend.

        :param api_url: Backend base URL using HTTPS or local HTTP.
        :param administrator_secret: Dedicated pilot administrator secret.
        :param method: HTTP method for the administration operation.
        :param endpoint_path: Protected administration endpoint path.
        :param request_body: Optional JSON request object.

        :return: Decoded JSON response or ``None`` for HTTP 204.

        :raises TypeError: If the server response has an invalid JSON type.
        :raises ValueError: If the URL, status or response is invalid.
        :raises OSError: If the backend cannot be reached.
        """
        parsed_url = MosaicAdminCli._validate_api_url(api_url)
        connection_type = (
            HTTPSConnection
            if parsed_url.scheme == 'https'
            else HTTPConnection
        )
        connection = connection_type(
            parsed_url.hostname,
            parsed_url.port,
            timeout=30,
        )
        body = (
            json.dumps(request_body).encode('utf-8')
            if request_body is not None
            else None
        )
        base_path = parsed_url.path.rstrip('/')
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {administrator_secret}',
        }
        if body is not None:
            headers['Content-Type'] = 'application/json'

        try:
            connection.request(
                method,
                f'{base_path}{endpoint_path}',
                body=body,
                headers=headers,
            )
            response = connection.getresponse()
            if response.status < 200 or response.status >= 300:
                raise ValueError(
                    f'Administration request failed with HTTP '
                    f'{response.status}.'
                )
            if response.status == 204:
                return None
            response_body = response.read()
        finally:
            connection.close()

        try:
            decoded_response = json.loads(response_body)
        except json.JSONDecodeError as error:
            raise ValueError(
                'Administration response did not contain valid JSON.'
            ) from error
        if not isinstance(decoded_response, (dict, list)):
            raise TypeError(
                'Administration response must contain an object or list.'
            )
        return decoded_response

    @staticmethod
    def _validate_api_url(api_url: str) -> SplitResult:
        """
        Require HTTPS except for an explicit loopback development address.

        :param api_url: Operator-supplied backend base URL.

        :return: Parsed URL safe for direct non-redirecting requests.

        :raises ValueError: If the URL is unsafe or malformed.
        """
        parsed_url = urlsplit(api_url)
        if (
            not parsed_url.hostname
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise ValueError('MOSAIC API URL is invalid.')
        loopback_hosts = {'127.0.0.1', '::1', 'localhost'}
        if parsed_url.scheme != 'https' and not (
            parsed_url.scheme == 'http'
            and parsed_url.hostname in loopback_hosts
        ):
            raise ValueError(
                'MOSAIC API URL must use HTTPS except on loopback.'
            )
        return parsed_url
