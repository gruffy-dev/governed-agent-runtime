"""Agent tools that make cross-turn goal transitions explicit."""

from pydantic import BaseModel, ConfigDict


class GoalOrchestrationTools(BaseModel):
    """Expose explicit transitions enforced by orchestration callbacks."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    def continue_goal_execution(
        self,
        missing_required_capability_names: list[str],
    ) -> dict[str, object]:
        """
        Return a runtime reminder when the model finishes prematurely.

        This tool is invoked by the completion guard rather than selected by
        the model. Its response starts another ADK model step with the exact
        required capabilities that remain outstanding.

        :param missing_required_capability_names: Required capability names that
            have not reached a terminal execution status.

        :return: A continuation directive containing normalised missing names.

        :raises ValueError: If no non-empty capability name was supplied.
        """
        normalised_names = list(
            dict.fromkeys(
                name.strip().lower()
                for name in missing_required_capability_names
                if isinstance(name, str) and name.strip()
            )
        )
        if not normalised_names:
            raise ValueError(
                'missing_required_capability_names must not be empty.'
            )
        return {
            'status': 'capability_execution_required',
            'missing_required_capability_names': normalised_names,
            'message': (
                'Execute every listed required capability before responding. '
                'If a required input is unavailable, call '
                'request_goal_clarification.'
            ),
        }

    def request_goal_clarification(self, question: str) -> dict[str, object]:
        """Record that the current goal cannot continue without user input.

        Use this tool only when a required value cannot be obtained from the
        conversation or available capability evidence. After calling it, ask
        the returned question and stop. Do not continue with other tools until
        the user replies.

        Args:
            question: The single concise question the user must answer.

        Returns:
            Acknowledgement that the goal is awaiting clarification. The ADA
            tool callback persists the transition in session state.

        Raises:
            ValueError: If the question is empty or contains only whitespace.
        """
        normalised_question = question.strip()
        if not normalised_question:
            raise ValueError('question must not be empty.')
        return {
            'status': 'awaiting_clarification',
            'question': normalised_question,
        }
