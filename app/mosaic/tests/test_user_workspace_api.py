import unittest
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mosaic.backend import Backend
from mosaic.components.api.user_workspace_api import UserWorkspaceApi
from mosaic.components.identity.pilot_user_administration_service import PilotUserAdministrationService
from mosaic.components.persistence.mosaic_database import MosaicDatabase
from mosaic.components.persistence.user_access_repository import UserAccessRepository
from mosaic.components.persistence.workspace_service import WorkspaceService
from mosaic.models.identity.pilot_administration_configuration import PilotAdministrationConfiguration
from mosaic.models.identity.pilot_authentication_configuration import PilotAuthenticationConfiguration
from mosaic.models.mosaic_database_configuration import MosaicDatabaseConfiguration
from mosaic.models.skills.skill import Skill
from mosaic.models.skills.skill_catalogue_group import SkillCatalogueGroup
from mosaic.models.skills.skill_catalogue_snapshot import SkillCatalogueSnapshot


class TestUserWorkspaceApi(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        configuration = MosaicDatabaseConfiguration(
            database_path=Path(self.directory.name) / 'mosaic.db'
        )
        self.snapshot = SkillCatalogueSnapshot(
            commit_sha='a' * 40,
            loaded_at=datetime.now(UTC),
            skills=tuple(
                Skill(
                    name=name,
                    version='1.0.0',
                    kind='procedural',
                    description='Synthetic description.',
                    instruction='Private synthetic instruction.',
                )
                for name in ('skill-a', 'skill-b')
            ),
            groups=(
                SkillCatalogueGroup(
                    group_id='synthetic-domain', skill_ids=('skill-a', 'skill-b')
                ),
                SkillCatalogueGroup(
                    group_id='synthetic-domain/first-function', skill_ids=('skill-a',)
                ),
                SkillCatalogueGroup(group_id='other-domain', skill_ids=('skill-b',)),
            ),
        )
        self.application = Backend.create_application(
            ada_app_factory=FastAPI,
            database_configuration=configuration,
            pilot_administration_configuration=PilotAdministrationConfiguration(
                enabled=False
            ),
            pilot_authentication_configuration=PilotAuthenticationConfiguration(
                mode='local', secure_cookie=False
            ),
            skill_catalogue_snapshot=self.snapshot,
        )
        self.database = MosaicDatabase(configuration)
        self.addCleanup(self.database.dispose)
        self.administration = PilotUserAdministrationService(
            self.database, self.snapshot
        )
        self.user_a = self.administration.create_user('synthetic-user-a')
        self.user_b = self.administration.create_user('synthetic-user-b')
        with self.database.create_session() as session, session.begin():
            service = WorkspaceService(session)
            service.replace_skill_ids(
                self.user_a.user_id,
                1,
                ('skill-a', 'withdrawn-skill'),
                datetime.now(UTC),
            )
            service.replace_skill_ids(
                self.user_b.user_id, 1, ('skill-b',), datetime.now(UTC)
            )
        self.client = TestClient(self.application, raise_server_exceptions=False)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_bearer_users_receive_only_owned_safe_metadata(self) -> None:
        for user, expected in ((self.user_a, 'skill-a'), (self.user_b, 'skill-b')):
            response = self.client.get(
                '/api/v1/workspace?user_id=untrusted-user',
                headers={'Authorization': f'Bearer {user.plaintext_token.get_secret_value()}'},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            body = response.json()
            self.assertEqual(
                set(body), {'user_id', 'workspace_id', 'version', 'skills'}
            )
            self.assertEqual(body['user_id'], user.user_id)
            self.assertEqual(body['workspace_id'], user.workspace_id)
            self.assertEqual(body['version'], 2)
            self.assertEqual(
                [skill['skill_id'] for skill in body['skills']], [expected]
            )
            skill = body['skills'][0]
            self.assertEqual(
                set(skill),
                {'skill_id', 'display_name', 'description', 'kind', 'groups'},
            )
            self.assertEqual(
                skill['display_name'], expected.replace('-', ' ').capitalize()
            )
            self.assertEqual(skill['description'], 'Synthetic description.')
            self.assertEqual(skill['kind'], 'procedural')
            self.assertNotIn('Private synthetic instruction.', response.text)
            self.assertNotIn(user.plaintext_token.get_secret_value(), response.text)
            self.assertNotIn('withdrawn-skill', response.text)
            expected_groups = (
                ['synthetic-domain', 'synthetic-domain/first-function']
                if expected == 'skill-a'
                else ['other-domain', 'synthetic-domain']
            )
            self.assertEqual(skill['groups'], expected_groups)

    def test_cookie_sign_out_and_different_user_sign_in_change_workspace(self) -> None:
        for user, skill_id in ((self.user_a, 'skill-a'), (self.user_b, 'skill-b')):
            self.assertEqual(
                self.client.post(
                    '/api/v1/auth/token', json={'token': user.plaintext_token.get_secret_value()}
                ).status_code,
                204,
            )
            body = self.client.get('/api/v1/workspace').json()
            self.assertEqual(body['user_id'], user.user_id)
            self.assertEqual(
                [skill['skill_id'] for skill in body['skills']], [skill_id]
            )
            self.assertEqual(self.client.post('/api/v1/auth/logout').status_code, 204)
            self.assertEqual(self.client.get('/api/v1/workspace').status_code, 401)

    def test_assignment_updates_are_visible_without_restart(self) -> None:
        with self.database.create_session() as session, session.begin():
            WorkspaceService(session).replace_skill_ids(
                self.user_a.user_id, 2, ('skill-b',), datetime.now(UTC)
            )
        response = self.client.get(
            '/api/v1/workspace',
            headers={'Authorization': f'Bearer {self.user_a.plaintext_token.get_secret_value()}'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['version'], 3)
        self.assertEqual(
            [skill['skill_id'] for skill in response.json()['skills']], ['skill-b']
        )

    def test_empty_and_missing_workspaces_do_not_load_catalogue(self) -> None:
        with self.database.create_session() as session, session.begin():
            WorkspaceService(session).replace_skill_ids(
                self.user_b.user_id, 2, (), datetime.now(UTC)
            )
            repository = UserAccessRepository(session)
            repository.add_user('synthetic-unassigned-user', datetime.now(UTC))
            token = token_urlsafe(32)
            repository.add_access_token(
                str(uuid4()), 'synthetic-unassigned-user', token, datetime.now(UTC)
            )
        with patch.object(
            UserWorkspaceApi,
            '_get_catalogue',
            side_effect=AssertionError('No catalogue import expected.'),
        ):
            for credential, missing in (
                (self.user_b.plaintext_token.get_secret_value(), False),
                (token, True),
            ):
                response = self.client.get(
                    '/api/v1/workspace',
                    headers={'Authorization': f'Bearer {credential}'},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['skills'], [])
                self.assertEqual(response.json()['workspace_id'] is None, missing)
                self.assertEqual(response.json()['version'] is None, missing)

    def test_anonymous_disabled_and_read_only_boundaries(self) -> None:
        self.assertEqual(self.client.get('/api/v1/workspace').status_code, 401)
        for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            response = self.client.request(
                method,
                '/api/v1/workspace',
                headers={'Authorization': f'Bearer {self.user_a.plaintext_token.get_secret_value()}'},
                json={'skills': []},
            )
            self.assertEqual(response.status_code, 405)
        self.administration.disable_user(self.user_a.user_id)
        self.assertEqual(
            self.client.get(
                '/api/v1/workspace',
                headers={'Authorization': f'Bearer {self.user_a.plaintext_token.get_secret_value()}'},
            ).status_code,
            401,
        )

    def test_catalogue_failure_is_not_reported_as_an_empty_workspace(self) -> None:
        with patch.object(
            UserWorkspaceApi,
            '_get_catalogue',
            side_effect=ValueError('Private synthetic diagnostic.'),
        ):
            response = self.client.get(
                '/api/v1/workspace',
                headers={'Authorization': f'Bearer {self.user_a.plaintext_token.get_secret_value()}'},
            )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertNotIn('Private synthetic diagnostic.', response.text)
        self.assertNotIn('skills', response.json())
