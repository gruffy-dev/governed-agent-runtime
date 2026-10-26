"""Agent tools that make cross-turn goal transitions explicit."""

from pydantic import BaseModel, ConfigDict


class GoalOrchestrationTools(BaseModel):
    """Expose explicit transitions enforced by orchestration callbacks."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

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
