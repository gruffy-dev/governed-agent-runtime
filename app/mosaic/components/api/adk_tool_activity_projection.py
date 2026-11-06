import re
from typing import Any


class AdkToolActivityProjection:
    def __init__(self) -> None:
        """
        Track bounded tool correlations for one public response stream only.
        """
        self._pending: dict[str, tuple[str, str | None]] = {}
        self._seen: set[str] = set()
        self._declared: set[str] = set()
        self._available: set[str] = set()
        self._sequence = 0

    def project(self, part: dict[str, Any], role: str) -> dict[str, Any] | None:
        """
        Preserve native tool shape with only allowlisted activity metadata.

        :param part: Private ADK part, whose arguments and results remain private.
        :param role: Native content role already admitted by the stream boundary.

        :return: Redacted native part, or None for unsupported or unmatched activity.
        """
        if part.get('thought'):
            return None
        call = part.get('functionCall', part.get('function_call'))
        if role == 'model' and isinstance(call, dict):
            return self._call(call)
        response = part.get('functionResponse', part.get('function_response'))
        if role in ('user', 'tool') and isinstance(response, dict):
            return self._response(response)
        return None

    def _call(self, call: dict[str, Any]) -> dict[str, Any] | None:
        """
        Admit known MOSAIC operations and discard all general tool arguments.

        :param call: Private function call from the public agent.

        :return: Native call with a known capability reference when available.
        """
        name = call.get('name')
        if (
            name
            not in (
                'discover_skills',
                'load_skills',
                'discover_capabilities',
                'execute_capability',
                'request_goal_clarification',
            )
            or len(self._pending) >= 64
            or len(self._seen) >= 512
        ):
            return None
        identifier = self._identifier(call.get('id'))
        if identifier is not None and identifier in self._seen:
            return None
        self._sequence += 1
        self._pending[identifier or f'pending:{self._sequence}'] = (name, identifier)
        public: dict[str, Any] = {'name': name, 'args': {}}
        if identifier is not None:
            self._seen.add(identifier)
            public['id'] = identifier
        arguments = call.get('args')
        if name == 'execute_capability' and isinstance(arguments, dict):
            capability_name = arguments.get('capability_name')
            if isinstance(capability_name, str) and capability_name in self._available:
                public['args'] = {'capability_name': capability_name}
        return {'functionCall': public}

    def _response(self, response: dict[str, Any]) -> dict[str, Any] | None:
        """
        Admit matched results with selection metadata but no instructions or evidence.

        :param response: Private native function response.

        :return: Redacted response, or None when it cannot be correlated safely.
        """
        identifier = self._identifier(response.get('id'))
        key = identifier
        if key is None:
            matches = [
                key
                for key, (name, _) in self._pending.items()
                if name == response.get('name')
            ]
            if len(matches) != 1:
                return None
            key = matches[0]
        pending = self._pending.get(key)
        if pending is None or pending[0] != response.get('name'):
            return None
        del self._pending[key]
        name, original_identifier = pending
        raw = response.get('response')
        public: dict[str, Any] = {}
        if isinstance(raw, dict):
            status = raw.get('status')
            if status in (
                'loaded',
                'available',
                'awaiting_clarification',
                'target_required',
                'target_unknown',
                'target_ambiguous',
            ):
                public['status'] = status
            if name == 'load_skills' and status == 'loaded':
                public['loaded_skills'] = self._skills(raw.get('loaded_skills'))
            if name == 'discover_capabilities' and status == 'available':
                public['capabilities'] = self._capabilities(raw.get('capabilities'))
        result: dict[str, Any] = {'name': name, 'response': public}
        if original_identifier is not None:
            result['id'] = original_identifier
        return {'functionResponse': result}

    def _skills(self, value: Any) -> list[dict[str, Any]]:
        """
        Retain confirmed Skill names and their declared semantic references only.

        :param value: Successful private Skill load list.

        :return: Bounded selection metadata without package bodies or forms.
        """
        self._declared.clear()
        self._available.clear()
        result = []
        for skill in value[:32] if isinstance(value, list) else []:
            if not isinstance(skill, dict) or not isinstance(skill.get('name'), str):
                continue
            if re.fullmatch(r'[a-z][a-z0-9-]{0,99}', skill['name']) is None:
                continue
            public: dict[str, Any] = {'name': skill['name']}
            for field in ('required_capability_names', 'optional_capability_names'):
                names = skill.get(field)
                public[field] = []
                for name in names[:256] if isinstance(names, list) else []:
                    if (
                        isinstance(name, str)
                        and len(name) <= 160
                        and re.fullmatch(r'[a-z][a-z0-9]*(?:\.[a-z0-9]+)+', name)
                        and len(self._declared) < 256
                    ):
                        public[field].append(name)
                        self._declared.add(name)
            result.append(public)
        return result

    def _capabilities(self, value: Any) -> list[dict[str, Any]]:
        """
        Retain descriptions only for available, Skill-declared capabilities.

        :param value: Successful private capability-discovery list.

        :return: Bounded provider-free descriptions suitable for progress display.
        """
        self._available.clear()
        result = []
        for capability in value[:256] if isinstance(value, list) else []:
            if (
                not isinstance(capability, dict)
                or capability.get('available') is not True
            ):
                continue
            name, description = capability.get('name'), capability.get('description')
            if not isinstance(name, str) or name not in self._declared:
                continue
            if (
                not isinstance(description, str)
                or not description.strip()
                or len(description) > 240
                or re.search(
                    r'[\x00-\x1f\x7f<>/@\\]|https?:|\b(?:[\w-]+\.)+[\w-]+\b',
                    description,
                    re.IGNORECASE,
                )
            ):
                continue
            self._available.add(name)
            result.append(
                {'name': name, 'description': description.strip(), 'available': True}
            )
        return result

    @staticmethod
    def _identifier(value: Any) -> str | None:
        """
        Accept bounded native call identifiers without forwarding arbitrary payloads.

        :param value: Optional native function-call or response identifier.

        :return: Valid correlation identifier or None for conservative name matching.
        """
        return (
            value
            if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,200}', value)
            else None
        )
