"""ADA callback controller for goal-scoped orchestration transitions."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ...interfaces.orchestration.callback_context_protocol import CallbackContextProtocol
from ...interfaces.orchestration.tool_protocol import ToolProtocol
from ...models.capabilities.target_resolution_candidate import TargetResolutionCandidate
from ...models.orchestration.orchestration_state import OrchestrationState
from .concurrent_session_invocation_error import ConcurrentSessionInvocationError


class OrchestrationTransitionController(BaseModel):
    """Persist goal state and enforce tool-ordering invariants through ADA."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    state_key: str = Field(
        default='mosaic:orchestration',
        description='ADA session-state key containing MOSAIC goal state.',
        min_length=1,
    )

    def before_agent_callback(
        self,
        callback_context: CallbackContextProtocol,
    ) -> None:
        """Start a new goal or resume one awaiting user clarification.

        Args:
            callback_context: ADA callback context for the new invocation.

        Raises:
            ConcurrentSessionInvocationError: If another invocation remains
                active for the session goal.
        """
        current = self._read_state(callback_context)
        invocation_id = callback_context.invocation_id

        if current is None or current.phase == 'completed':
            self._write_state(
                callback_context,
                OrchestrationState.start(invocation_id),
            )
            return

        if current.phase == 'awaiting_clarification':
            self._write_state(
                callback_context,
                current.model_copy(
                    update={
                        'active_invocation_id': invocation_id,
                        'phase': 'planning',
                        'clarification_question': None,
                    }
                ),
            )
            return

        if current.active_invocation_id != invocation_id:
            raise ConcurrentSessionInvocationError(
                'This session already has an active MOSAIC invocation.'
            )

    def after_agent_callback(
        self,
        callback_context: CallbackContextProtocol,
    ) -> None:
        """Complete a goal after every required capability has terminated.

        Args:
            callback_context: ADA callback context for the ending invocation.

        Raises:
            RuntimeError: If orchestration state was not initialized.
            ConcurrentSessionInvocationError: If another invocation replaced
                the active invocation before completion.
        """
        current = self._require_state(callback_context)
        if current.phase == 'awaiting_clarification':
            return
        if not current.skill_discovery_completed:
            raise RuntimeError(
                'The agent ended before automatic skill discovery completed.'
            )
        if current.active_invocation_id != callback_context.invocation_id:
            raise ConcurrentSessionInvocationError(
                'The active MOSAIC invocation changed before completion.'
            )
        incomplete_required_capabilities = (
            set(current.required_capability_names)
            - set(current.required_capability_outcomes.keys())
        )
        if incomplete_required_capabilities:
            raise RuntimeError(
                'The agent ended while required capabilities remain: '
                + ', '.join(sorted(incomplete_required_capabilities))
            )
        self._write_state(
            callback_context,
            current.model_copy(update={'phase': 'completed'}),
        )

    def incomplete_required_capability_names(
        self,
        callback_context: CallbackContextProtocol,
    ) -> tuple[str, ...]:
        """Return required capabilities still pending for active execution.

        Args:
            callback_context: ADA callback context for the current invocation.

        Returns:
            Missing capability names in their declared order. An empty tuple
            is returned while awaiting explicit user clarification.

        Raises:
            RuntimeError: If orchestration state was not initialized.
            ConcurrentSessionInvocationError: If another invocation owns the
                active goal.
        """
        current = self._require_active_state(callback_context)
        if current.phase == 'awaiting_clarification':
            return ()
        completed_names = set(current.required_capability_outcomes.keys())
        return tuple(
            name
            for name in current.required_capability_names
            if name not in completed_names
        )

    def required_capability_limitations(
        self,
        callback_context: CallbackContextProtocol,
    ) -> dict[str, str]:
        """Return terminal non-success outcomes for required capabilities.

        Args:
            callback_context: ADA context for the current invocation.

        Returns:
            A new mapping of required capability names to limiting outcomes.

        Raises:
            RuntimeError: If orchestration state was not initialized.
            ConcurrentSessionInvocationError: If another invocation owns the
                active goal.
        """
        current = self._require_active_state(callback_context)
        return {
            name: outcome
            for name, outcome in current.required_capability_outcomes.items()
            if outcome != 'success'
        }

    def skill_discovery_required(
        self,
        callback_context: CallbackContextProtocol,
    ) -> bool:
        """Return whether the active goal still requires skill discovery.

        Args:
            callback_context: ADA callback context for the current invocation.

        Returns:
            ``True`` until authorised metadata has been discovered once.

        Raises:
            RuntimeError: If orchestration state was not initialized.
            ConcurrentSessionInvocationError: If another invocation owns the
                active goal.
        """
        return not self._require_active_state(
            callback_context
        ).skill_discovery_completed

    def before_tool_callback(
        self,
        tool: ToolProtocol,
        args: dict[str, object],
        tool_context: CallbackContextProtocol,
    ) -> dict[str, object] | None:
        """Enforce discovery, single-batch loading, and clarification pauses.

        Args:
            tool: ADA tool about to be invoked.
            args: Semantic arguments prepared for the tool.
            tool_context: ADA context for the current tool invocation.

        Returns:
            A short-circuit result when the tool call is blocked, otherwise
            ``None`` so ADA executes the tool normally.

        Raises:
            RuntimeError: If orchestration state was not initialized.
            ConcurrentSessionInvocationError: If the tool does not belong to
                the active invocation.
        """
        current = self._require_active_state(tool_context)
        tool_name = tool.name

        if current.phase == 'awaiting_clarification':
            return {
                'status': 'blocked_awaiting_clarification',
                'clarification_question': current.clarification_question,
            }

        if tool_name == 'discover_skills':
            if current.skill_discovery_completed:
                return {'status': 'skill_discovery_already_completed'}
            return None

        if (
            tool_name
            in {
                'load_skills',
                'discover_capabilities',
                'execute_capability',
                'request_goal_clarification',
            }
            and not current.skill_discovery_completed
        ):
            return {
                'status': 'skill_discovery_required',
                'message': (
                    'Complete automatic skill discovery before loading '
                    'skills, discovering capabilities, requesting '
                    'clarification, or executing a capability.'
                ),
            }

        if tool_name == 'load_skills' and current.capability_discovery_attempted:
            return {
                'status': 'skill_selection_already_completed',
                'message': (
                    'Capability discovery has already finalized skill '
                    'selection for this goal.'
                ),
            }

        if tool_name == 'load_skills' and current.skill_batch_attempted:
            return {
                'status': 'skill_batch_already_attempted',
                'requested_skill_names': list(
                    current.requested_skill_names
                ),
                'loaded_skill_names': list(current.loaded_skill_names),
            }

        if (
            tool_name in {'discover_capabilities', 'execute_capability'}
            and not current.skill_batch_loaded
        ):
            return {
                'status': 'capability_skill_required',
                'message': (
                    'Load a relevant skill before discovering or executing '
                    'semantic capabilities.'
                ),
            }

        if tool_name == 'discover_capabilities':
            if current.capability_discovery_attempted:
                return {
                    'status': 'capability_discovery_already_attempted',
                    'candidate_capability_names': list(
                        current.candidate_capability_names
                    ),
                }
            return None

        if tool_name == 'execute_capability':
            if not current.capability_discovery_completed:
                return {
                    'status': 'capability_discovery_required',
                    'message': (
                        'Call discover_capabilities before executing a '
                        'semantic capability.'
                    ),
                }
            capability_name = args.get('capability_name')
            normalized_name = (
                capability_name.strip().lower()
                if isinstance(capability_name, str)
                else ''
            )
            if normalized_name not in current.candidate_capability_names:
                return {
                    'status': 'capability_not_authorized_for_goal',
                    'capability_name': normalized_name or '<invalid>',
                }

        if tool_name == 'execute_capability' and current.phase == 'planning':
            self._write_state(
                tool_context,
                current.model_copy(update={'phase': 'executing'}),
            )

        return None

    def after_tool_callback(
        self,
        tool: ToolProtocol,
        args: dict[str, object],
        tool_context: CallbackContextProtocol,
        tool_response: dict[str, object],
    ) -> None:
        """Commit successful tool transitions to ADA-managed session state.

        Args:
            tool: ADA tool that completed.
            args: Semantic arguments supplied to the tool.
            tool_context: ADA context for the current tool invocation.
            tool_response: Serialized result returned by the tool.

        Raises:
            ValueError: If a clarification tool call has no valid question.
            RuntimeError: If orchestration state was not initialized.
            ConcurrentSessionInvocationError: If the tool does not belong to
                the active invocation.
        """
        current = self._require_active_state(tool_context)

        if tool.name == 'discover_skills':
            if (
                not current.skill_discovery_completed
                and tool_response.get('status')
                in {'available', 'none_available'}
            ):
                self._write_state(
                    tool_context,
                    current.model_copy(
                        update={'skill_discovery_completed': True}
                    ),
                )
        elif tool.name == 'load_skills':
            if not current.skill_discovery_completed:
                return
            if current.skill_batch_attempted:
                return
            requested_names = self._normalized_names(args.get('skill_names'))
            status = tool_response.get('status')
            loaded_names = (
                self._loaded_names(tool_response)
                if status == 'loaded'
                else ()
            )
            required_capability_names = (
                self._declared_capability_names(
                    tool_response,
                    'required_capability_names',
                )
                if status == 'loaded'
                else ()
            )
            required_name_set = set(required_capability_names)
            optional_capability_names = (
                tuple(
                    name
                    for name in self._declared_capability_names(
                        tool_response,
                        'optional_capability_names',
                    )
                    if name not in required_name_set
                )
                if status == 'loaded'
                else ()
            )
            self._write_state(
                tool_context,
                current.model_copy(
                    update={
                        'phase': 'executing',
                        'skill_batch_attempted': True,
                        'skill_batch_loaded': status == 'loaded',
                        'requested_skill_names': requested_names,
                        'loaded_skill_names': loaded_names,
                        'required_capability_names': (
                            required_capability_names
                        ),
                        'optional_capability_names': (
                            optional_capability_names
                        ),
                        'capability_discovery_attempted': False,
                        'capability_discovery_completed': False,
                        'candidate_capability_names': (),
                    }
                ),
            )
        elif tool.name == 'discover_capabilities':
            if current.capability_discovery_attempted:
                return
            status = tool_response.get('status')
            if not isinstance(status, str) or status not in {
                'available',
                'none_available',
                'limit_exceeded',
                'required_capabilities_unavailable',
            }:
                return
            candidate_names = (
                self._candidate_capability_names(tool_response)
                if status in {'available', 'none_available'}
                else ()
            )
            target_update: dict[str, str | None] = {}
            target_value = tool_response.get('target')
            if target_value is not None:
                target = TargetResolutionCandidate.model_validate(
                    target_value
                )
                if (
                    current.target_id is not None
                    and current.target_id != target.target_id
                ):
                    raise RuntimeError(
                        'Capability discovery cannot replace a goal target.'
                    )
                target_update = {
                    'target_id': target.target_id,
                    'target_display_name': target.display_name,
                }
            self._write_state(
                tool_context,
                current.model_copy(
                    update={
                        **target_update,
                        'capability_discovery_attempted': True,
                        'capability_discovery_completed': status
                        in {'available', 'none_available'},
                        'candidate_capability_names': candidate_names,
                        'required_capability_outcome_records': (
                            {
                                **current.required_capability_outcome_records,
                                **{
                                    name: (current.goal_id, status)
                                    for name in (
                                        current.required_capability_names
                                    )
                                },
                            }
                            if status
                            in {
                                'limit_exceeded',
                                'required_capabilities_unavailable',
                            }
                            else (
                                current.required_capability_outcome_records
                            )
                        ),
                    }
                ),
            )
        elif tool.name == 'execute_capability':
            self._record_capability_result(
                args=args,
                tool_context=tool_context,
                tool_response=tool_response,
                current=current,
            )
        elif tool.name == 'request_goal_clarification':
            question = args.get('question')
            if not isinstance(question, str) or not question.strip():
                raise ValueError(
                    'A clarification transition requires a question.'
                )
            self._write_state(
                tool_context,
                current.model_copy(
                    update={
                        'phase': 'awaiting_clarification',
                        'clarification_question': question.strip(),
                    }
                ),
            )

    def _read_state(
        self,
        context: CallbackContextProtocol,
    ) -> OrchestrationState | None:
        """Read and validate MOSAIC state from an ADA callback context.

        Args:
            context: ADA callback or tool context containing session state.

        Returns:
            Validated state, or ``None`` when a goal has not been initialized.

        Raises:
            pydantic.ValidationError: If persisted state is malformed.
        """
        raw_state = context.state.get(self.state_key)
        if raw_state is None:
            return None
        return OrchestrationState.model_validate(raw_state)

    def _require_state(
        self,
        context: CallbackContextProtocol,
    ) -> OrchestrationState:
        """Return initialized orchestration state.

        Args:
            context: ADA callback or tool context containing session state.

        Returns:
            Validated initialized orchestration state.

        Raises:
            RuntimeError: If no orchestration state has been initialized.
            pydantic.ValidationError: If persisted state is malformed.
        """
        state = self._read_state(context)
        if state is None:
            raise RuntimeError('MOSAIC orchestration state is not initialized.')
        return state

    def _require_active_state(
        self,
        context: CallbackContextProtocol,
    ) -> OrchestrationState:
        """Return state owned by the current ADA invocation.

        Args:
            context: ADA callback or tool context for the current invocation.

        Returns:
            Validated state owned by the current invocation.

        Raises:
            RuntimeError: If no orchestration state has been initialized.
            ConcurrentSessionInvocationError: If another invocation owns the
                active goal.
        """
        state = self._require_state(context)
        if state.active_invocation_id != context.invocation_id:
            raise ConcurrentSessionInvocationError(
                'This tool call does not belong to the active invocation.'
            )
        return state

    def _write_state(
        self,
        context: CallbackContextProtocol,
        state: OrchestrationState,
    ) -> None:
        """Validate and write JSON-compatible state through ADA.

        Args:
            context: ADA callback or tool context receiving the state update.
            state: Candidate orchestration state to validate and persist.

        Raises:
            pydantic.ValidationError: If the candidate state is malformed.
        """
        validated_state = OrchestrationState.model_validate(
            state.model_dump(mode='python')
        )
        context.state[self.state_key] = validated_state.model_dump(mode='json')

    def _normalized_names(self, value: object) -> tuple[str, ...]:
        """Normalize a JSON skill-name list while preserving order.

        Args:
            value: Untrusted tool argument expected to contain skill names.

        Returns:
            Unique normalized names, or an empty tuple for a non-list value.
        """
        if not isinstance(value, list):
            return ()
        return tuple(
            dict.fromkeys(
                name.strip().lower()
                for name in value
                if isinstance(name, str) and name.strip()
            )
        )

    def _loaded_names(
        self,
        tool_response: dict[str, object],
    ) -> tuple[str, ...]:
        """Extract approved skill names from a loader response.

        Args:
            tool_response: Serialized response returned by ``load_skills``.

        Returns:
            Skill names present in valid loaded-skill entries.
        """
        loaded_skills = tool_response.get('loaded_skills')
        if not isinstance(loaded_skills, list):
            return ()
        return tuple(
            item['name']
            for item in loaded_skills
            if isinstance(item, dict)
            and isinstance(item.get('name'), str)
        )

    def _declared_capability_names(
        self,
        tool_response: dict[str, object],
        field_name: Literal[
            'required_capability_names',
            'optional_capability_names',
        ],
    ) -> tuple[str, ...]:
        """Extract one capability declaration from loaded skills.

        Args:
            tool_response: Serialized response returned by ``load_skills``.
            field_name: Required or optional capability declaration to read.

        Returns:
            Unique normalized capability names in declaration order.
        """
        loaded_skills = tool_response.get('loaded_skills')
        if not isinstance(loaded_skills, list):
            return ()

        names: list[str] = []
        for skill in loaded_skills:
            if not isinstance(skill, dict):
                continue
            capability_names = skill.get(field_name)
            if not isinstance(capability_names, (list, tuple)):
                continue
            names.extend(
                name.strip().lower()
                for name in capability_names
                if isinstance(name, str) and name.strip()
            )
        return tuple(dict.fromkeys(names))

    def _candidate_capability_names(
        self,
        tool_response: dict[str, object],
    ) -> tuple[str, ...]:
        """Extract authorised semantic names from discovery metadata.

        Args:
            tool_response: Serialized capability-discovery response.

        Returns:
            Unique normalized candidate names in response order.
        """
        capabilities = tool_response.get('capabilities')
        if not isinstance(capabilities, list):
            return ()
        return tuple(
            dict.fromkeys(
                name.strip().lower()
                for item in capabilities
                if isinstance(item, dict)
                and isinstance((name := item.get('name')), str)
                and name.strip()
            )
        )

    def _record_capability_result(
        self,
        args: dict[str, object],
        tool_context: CallbackContextProtocol,
        tool_response: dict[str, object],
        current: OrchestrationState,
    ) -> None:
        """Record a terminal result for one required capability.

        Missing or invalid arguments are deliberately non-terminal because the
        same goal must continue after the user supplies corrected input.

        Args:
            args: Semantic arguments supplied to ``execute_capability``.
            tool_context: ADA context receiving the state transition.
            tool_response: Serialized capability execution result.
            current: Validated orchestration state before the transition.
        """
        capability_name = args.get('capability_name')
        status = tool_response.get('status')
        terminal_statuses = {
            'success',
            'unavailable',
            'evidence_too_large',
            'failed',
            'timed_out',
        }
        if (
            not isinstance(capability_name, str)
            or not isinstance(status, str)
            or status not in terminal_statuses
            or not current.capability_discovery_completed
        ):
            return
        if tool_response.get('target_id') != current.target_id:
            raise RuntimeError(
                'Capability result target does not match the active goal.'
            )

        normalized_name = capability_name.strip().lower()
        if (
            normalized_name not in current.required_capability_names
            or normalized_name not in current.candidate_capability_names
        ):
            return

        required_capability_outcome_records = {
            **current.required_capability_outcome_records,
            normalized_name: (current.goal_id, status),
        }
        self._write_state(
            tool_context,
            current.model_copy(
                update={
                    'required_capability_outcome_records': (
                        required_capability_outcome_records
                    ),
                }
            ),
        )
