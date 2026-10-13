import json
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ..persistence.conversation_metadata_repository import ConversationMetadataRepository
from ..persistence.mosaic_database import MosaicDatabase
from ..persistence.user_record import UserRecord
from ..persistence.workspace_service import WorkspaceService
from ...models.identity.trusted_request_context import TrustedRequestContext
from ...models.mosaic_database_configuration import MosaicDatabaseConfiguration
from ...models.skills.session_skill_profile import SessionSkillProfile
from ...models.skills.skill_catalogue_snapshot import SkillCatalogueSnapshot
from ...models.skills.skill_loading_configuration import SkillLoadingConfiguration


class WorkspaceSkillProfileResolver(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    configuration: SkillLoadingConfiguration = Field(
        description='Existing discovery and loading limits.'
    )
    database_configuration: MosaicDatabaseConfiguration = Field(
        description='Configured MOSAIC workspace and ownership database.'
    )
    catalogue_snapshot: SkillCatalogueSnapshot = Field(
        description='Immutable catalogue supplying executable Skills.'
    )

    def resolve(
        self, context: TrustedRequestContext, conversation_id: UUID, goal_id: str
    ) -> SessionSkillProfile:
        """
        Snapshot an enabled user's workspace Skills for one new owned Goal.

        Missing workspaces grant nothing; absent catalogue references are withdrawn
        or unknown and cannot be executed. No deployment profile is a fallback.

        :param context: Identity derived from a privately dispatched ADA session.
        :param conversation_id: Owned public conversation UUID.
        :param goal_id: Goal identifier created by MOSAIC's orchestration callback.

        :return: Bounded immutable Skill profile tied to user, conversation and Goal.

        :raises ValueError: If ownership, user eligibility or exposure limits fail.
        """
        if not goal_id.strip():
            raise ValueError('A workspace Skill binding requires a Goal.')
        database = MosaicDatabase(self.database_configuration)
        try:
            with database.create_session() as session, session.begin():
                user = session.get(UserRecord, context.user_id)
                if user is None or not user.is_enabled:
                    raise ValueError(
                        'Workspace Skill binding requires an enabled owner.'
                    )
                if (
                    ConversationMetadataRepository(session).get_created_at(
                        context, conversation_id
                    )
                    is None
                ):
                    raise ValueError(
                        'Workspace Skill binding requires an owned conversation.'
                    )
                workspace = WorkspaceService(session).get_for_user(context.user_id)
        finally:
            database.dispose()
        assigned = set(() if workspace is None else workspace.skill_ids)
        allowed = tuple(
            sorted(
                skill.name
                for skill in self.catalogue_snapshot.skills
                if skill.name in assigned
            )
        )
        if len(allowed) > self.configuration.maximum_enabled_skill_count:
            raise ValueError('Workspace Skill count exceeded its limit.')
        metadata = [
            {
                'name': skill.name,
                'kind': skill.kind,
                'version': skill.version,
                'description': skill.description,
            }
            for skill in self.catalogue_snapshot.skills
            if skill.name in allowed
        ]
        if (
            len(json.dumps(metadata, ensure_ascii=False, separators=(',', ':')))
            > self.configuration.maximum_discovery_metadata_characters
        ):
            raise ValueError('Workspace Skill discovery metadata exceeded its limit.')
        return SessionSkillProfile(
            profile_id='workspace-unassigned'
            if workspace is None
            else f'workspace-{workspace.workspace_id}',
            allowed_skill_names=allowed,
            catalogue_commit_sha=self.catalogue_snapshot.commit_sha,
            goal_id=goal_id,
            user_id=context.user_id,
            app_name=context.app_name,
            session_id=str(conversation_id),
        )
