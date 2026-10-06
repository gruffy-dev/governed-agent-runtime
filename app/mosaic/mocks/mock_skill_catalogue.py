"""In-memory mock skill catalogue for the MOSAIC prototype."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from ..models.skills.skill import Skill


class MockSkillCatalogue(BaseModel):
    """Provide deterministic mock skills without a marketplace dependency."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    skills: tuple[Skill, ...] = Field(
        description='Deterministic skills exposed by the prototype.',
        min_length=1,
    )

    @classmethod
    def create(cls) -> Self:
        """Create the mock skill catalogue used by the prototype.

        Returns:
            A validated catalogue containing deterministic prototype skills.

        Raises:
            pydantic.ValidationError: If a configured mock skill or the
                resulting catalogue is invalid.
        """
        return cls(
            skills=(
                Skill(
                    name='create-engineering-onboarding-checklist',
                    version='1.0.0',
                    kind='procedural',
                    description=(
                        'Create a structured onboarding checklist for an '
                        'engineer joining a team or project.'
                    ),
                    instruction='''
Create an onboarding checklist tailored to the context supplied by the user.
Cover preparation before the start date, first-day access, the first week,
technical orientation, team practices, and follow-up. Do not invent
organisation-specific systems or policies that the user has not supplied.
'''.strip(),
                    output_form='''
Use headings for Before starting, First day, First week, Technical orientation,
Team practices, and Follow-up. Put actionable checkbox items under each heading.
'''.strip(),
                ),
                Skill(
                    name='investigate-openshift-ingress',
                    version='1.0.0',
                    kind='procedural',
                    description=(
                        'Investigate slow or failing ingress into an OpenShift '
                        'cluster using available read-only capabilities.'
                    ),
                    instruction='''
Treat ingress as the OpenShift router subsystem. Establish the cluster and time
window, locate the ingress controller and router pods, inspect their state and
events, review relevant router logs, and correlate the findings with available
latency, saturation, restart, CPU, memory, and network metrics. Ask for missing
context when it cannot be inferred. Do not invent unavailable observations.
'''.strip(),
                    output_form='''
Report the observed symptoms, likely cause, supporting evidence, uncertainty,
and recommended next read-only diagnostic step.
'''.strip(),
                    required_capability_names=(
                        'openshift.ingress.status.read',
                        'openshift.router.logs.read',
                        'prometheus.ingress.metrics.read',
                    ),
                ),
            ),
        )
