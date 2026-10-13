import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from uuid import uuid4

from mosaic.components.orchestration.orchestration_transition_controller import OrchestrationTransitionController
from mosaic.components.orchestration.mosaic_agent_callbacks import MosaicAgentCallbacks
from mosaic.components.persistence.conversation_metadata_repository import ConversationMetadataRepository
from mosaic.components.persistence.mosaic_database import MosaicDatabase
from mosaic.components.persistence.mosaic_database_migrator import MosaicDatabaseMigrator
from mosaic.components.persistence.user_access_repository import UserAccessRepository
from mosaic.components.persistence.user_record import UserRecord
from mosaic.components.persistence.workspace_service import WorkspaceService
from mosaic.components.skills.session_skill_profile_manager import SessionSkillProfileManager
from mosaic.components.skills.skill_discovery_and_loader import SkillDiscoveryAndLoader
from mosaic.components.skills.workspace_skill_profile_resolver import WorkspaceSkillProfileResolver
from mosaic.models.identity.trusted_request_context import TrustedRequestContext
from mosaic.models.mosaic_database_configuration import MosaicDatabaseConfiguration
from mosaic.models.orchestration.orchestration_state import OrchestrationState
from mosaic.models.skills.skill import Skill
from mosaic.models.skills.skill_catalogue_snapshot import SkillCatalogueSnapshot
from mosaic.models.skills.skill_loading_configuration import SkillLoadingConfiguration


class TestWorkspaceSkillProfileResolver(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.configuration = MosaicDatabaseConfiguration(
            database_path=Path(self.directory.name) / 'mosaic.db'
        )
        self.database = MosaicDatabase(self.configuration)
        self.addCleanup(self.database.dispose)
        MosaicDatabaseMigrator(self.database).upgrade()
        self.identity = TrustedRequestContext(
            app_name='synthetic-app', user_id='synthetic-user'
        )
        self.conversation_id = uuid4()
        self.snapshot = SkillCatalogueSnapshot(
            commit_sha='a' * 40,
            loaded_at=datetime.now(UTC),
            skills=tuple(
                Skill(
                    name=name,
                    kind='procedural',
                    version='1.0.0',
                    description='Synthetic skill.',
                    instruction='Synthetic guidance.',
                )
                for name in ('skill-a', 'skill-b')
            ),
        )
        self.resolver = WorkspaceSkillProfileResolver(
            configuration=SkillLoadingConfiguration(),
            database_configuration=self.configuration,
            catalogue_snapshot=self.snapshot,
        )
        with self.database.create_session() as session, session.begin():
            UserAccessRepository(session).add_user(
                self.identity.user_id, datetime.now(UTC)
            )
            UserAccessRepository(session).add_user('other-user', datetime.now(UTC))
            ConversationMetadataRepository(session).add(
                self.identity, self.conversation_id, datetime.now(UTC)
            )

    def assign(self, names: tuple[str, ...]) -> None:
        with self.database.create_session() as session, session.begin():
            service = WorkspaceService(session)
            workspace = service.get_for_user(self.identity.user_id)
            if workspace is None:
                workspace = service.create_for_user(
                    self.identity.user_id, datetime.now(UTC)
                )
            service.replace_skill_ids(
                self.identity.user_id, workspace.version, names, datetime.now(UTC)
            )

    def test_missing_empty_and_withdrawn_assignments_grant_nothing(self) -> None:
        self.assertEqual(
            self.resolver.resolve(
                self.identity, self.conversation_id, 'goal'
            ).allowed_skill_names,
            (),
        )
        self.assign(())
        self.assertEqual(
            self.resolver.resolve(
                self.identity, self.conversation_id, 'goal'
            ).allowed_skill_names,
            (),
        )
        self.assign(('withdrawn-skill', 'skill-b'))
        self.assertEqual(
            self.resolver.resolve(
                self.identity, self.conversation_id, 'goal'
            ).allowed_skill_names,
            ('skill-b',),
        )

    def test_foreign_owner_and_disabled_user_are_denied(self) -> None:
        with self.assertRaises(ValueError):
            self.resolver.resolve(
                TrustedRequestContext(
                    app_name=self.identity.app_name, user_id='other-user'
                ),
                self.conversation_id,
                'goal',
            )
        with self.database.create_session() as session, session.begin():
            session.get(UserRecord, self.identity.user_id).is_enabled = False
            session.get(UserRecord, self.identity.user_id).disabled_at = datetime.now(
                UTC
            )
        with self.assertRaises(ValueError):
            self.resolver.resolve(self.identity, self.conversation_id, 'goal')

    def test_binding_is_stable_through_clarification_and_refreshes_next_goal(
        self,
    ) -> None:
        self.assign(('skill-a',))
        controller = OrchestrationTransitionController()
        manager = SessionSkillProfileManager(resolver=self.resolver)
        context = SimpleNamespace(
            session=SimpleNamespace(
                id=str(self.conversation_id),
                app_name=self.identity.app_name,
                user_id=self.identity.user_id,
            ),
            invocation_id='first',
            state={},
        )
        callbacks = MosaicAgentCallbacks(profile_manager=manager, orchestration_controller=controller)
        callbacks.before_agent_callback(context)
        first = manager.ensure_profile(context)
        self.assign(('skill-b',))
        self.assertEqual(manager.ensure_profile(context), first)
        goal = OrchestrationState.model_validate(context.state[controller.state_key])
        context.state[controller.state_key] = goal.model_copy(
            update={
                'phase': 'awaiting_clarification',
                'skill_discovery_completed': True,
            }
        ).model_dump(mode='json')
        context.invocation_id = 'clarification'
        controller.before_agent_callback(context)
        self.assertEqual(manager.ensure_profile(context), first)
        controller.after_agent_callback(context)
        context.invocation_id = 'next'
        controller.before_agent_callback(context)
        next_profile = manager.ensure_profile(context)
        self.assertNotEqual(next_profile.goal_id, first.goal_id)
        self.assertEqual(next_profile.allowed_skill_names, ('skill-b',))

    def test_identity_cache_mismatch_and_missing_established_binding_fail_closed(
        self,
    ) -> None:
        controller = OrchestrationTransitionController()
        manager = SessionSkillProfileManager(resolver=self.resolver)
        context = SimpleNamespace(
            session=SimpleNamespace(
                id=str(self.conversation_id),
                app_name=self.identity.app_name,
                user_id=self.identity.user_id,
            ),
            invocation_id='first',
            state={},
        )
        controller.before_agent_callback(context)
        manager.ensure_profile(context)
        context.session.user_id = 'other-user'
        with self.assertRaises(ValueError):
            manager.ensure_profile(context)
        context.session.user_id = self.identity.user_id
        context.state.pop(manager.state_key)
        goal = OrchestrationState.model_validate(context.state[controller.state_key])
        context.state[controller.state_key] = goal.model_copy(
            update={'skill_discovery_completed': True}
        ).model_dump(mode='json')
        with self.assertRaises(ValueError):
            manager.ensure_profile(context)

    def test_exposure_limits_are_enforced(self) -> None:
        self.assign(('skill-a', 'skill-b'))
        for configuration in (
            SkillLoadingConfiguration(maximum_enabled_skill_count=1),
            SkillLoadingConfiguration(maximum_discovery_metadata_characters=1),
        ):
            resolver = self.resolver.model_copy(update={'configuration': configuration})
            with self.assertRaises(ValueError):
                resolver.resolve(self.identity, self.conversation_id, 'goal')

    def test_two_users_discover_and_load_only_their_own_skills(self) -> None:
        self.assign(('skill-a',))
        other_identity = TrustedRequestContext(
            app_name=self.identity.app_name, user_id='other-user'
        )
        other_conversation = uuid4()
        with self.database.create_session() as session, session.begin():
            service = WorkspaceService(session)
            workspace = service.create_for_user(
                other_identity.user_id, datetime.now(UTC)
            )
            service.replace_skill_ids(
                other_identity.user_id,
                workspace.version,
                ('skill-b',),
                datetime.now(UTC),
            )
            ConversationMetadataRepository(session).add(
                other_identity, other_conversation, datetime.now(UTC)
            )
        manager = SessionSkillProfileManager(resolver=self.resolver)
        loader = SkillDiscoveryAndLoader(
            skills=self.snapshot.skills, profile_manager=manager
        )
        for identity, conversation_id, allowed, forbidden in (
            (self.identity, self.conversation_id, 'skill-a', 'skill-b'),
            (other_identity, other_conversation, 'skill-b', 'skill-a'),
        ):
            context = SimpleNamespace(
                session=SimpleNamespace(
                    id=str(conversation_id),
                    app_name=identity.app_name,
                    user_id=identity.user_id,
                ),
                invocation_id='synthetic-invocation',
                state={},
            )
            OrchestrationTransitionController().before_agent_callback(context)
            self.assertEqual(
                [entry['name'] for entry in loader.discover_skills(context)['skills']],
                [allowed],
            )
            self.assertEqual(loader.load_skills([allowed], context)['status'], 'loaded')
            rejected = loader.load_skills([forbidden], context)
            self.assertEqual(rejected['status'], 'not_found')
            self.assertEqual(rejected['loaded_skills'], [])
