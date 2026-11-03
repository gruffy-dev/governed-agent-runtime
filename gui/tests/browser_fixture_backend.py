import json
import time
from datetime import UTC, datetime
from uuid import uuid4

from flask import Flask, Response, jsonify, request


class BrowserFixtureBackend:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}
        self.application = Flask(__name__)
        self.application.after_request(self.cors)
        self.application.add_url_rule(
            '/api/v1/auth/token', view_func=self.sign_in, methods=['POST', 'OPTIONS']
        )
        self.application.add_url_rule(
            '/api/v1/auth/logout', view_func=self.sign_out, methods=['POST', 'OPTIONS']
        )
        self.application.add_url_rule(
            '/api/v1/workspace', view_func=self.workspace, methods=['GET', 'OPTIONS']
        )
        self.application.add_url_rule(
            '/api/v1/conversations',
            view_func=self.conversations,
            methods=['GET', 'POST', 'OPTIONS'],
        )
        self.application.add_url_rule(
            '/api/v1/conversations/<identifier>',
            view_func=self.conversation,
            methods=['GET', 'OPTIONS'],
        )
        self.application.add_url_rule(
            '/api/v1/conversations/<identifier>/messages',
            view_func=self.stream,
            methods=['POST', 'OPTIONS'],
        )
        for owner in ('synthetic-user-a', 'synthetic-user-b'):
            record = self.create_record(owner)
            record.update(
                title='Synthetic saved conversation',
                messages=[
                    {'role': 'user', 'text': 'Show a saved answer.'},
                    {
                        'role': 'assistant',
                        'text': '## Saved summary\n\nThis history is synthetic browser-test data.\n\n```python\nprint("hello")\n```',
                    },
                ],
            )
            interrupted = self.create_record(owner)
            interrupted.update(
                title='Synthetic interrupted conversation',
                can_continue=False,
                is_interrupted=True,
                messages=[
                    {'role': 'user', 'text': 'This synthetic request was stopped.'}
                ],
            )

    def cors(self, response: Response) -> Response:
        response.headers['Access-Control-Allow-Origin'] = 'http://127.0.0.1:8050'
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST'
        response.headers['Access-Control-Expose-Headers'] = 'X-Correlation-ID'
        response.headers['X-Correlation-ID'] = str(uuid4())
        response.headers['Cache-Control'] = 'no-store'
        return response

    def owner(self) -> str | None:
        return {
            'synthetic-browser-a': 'synthetic-user-a',
            'synthetic-browser-b': 'synthetic-user-b',
        }.get(request.cookies.get('synthetic_test_session'))

    def sign_in(self) -> Response:
        if request.method == 'OPTIONS':
            return Response(status=200)
        token = request.get_json().get('token')
        if token not in {'synthetic-browser-a', 'synthetic-browser-b'}:
            return jsonify(detail='Unauthorised'), 401
        response = Response(status=204)
        response.set_cookie(
            'synthetic_test_session', token, httponly=True, samesite='Strict'
        )
        return response

    def sign_out(self) -> Response:
        response = Response(status=204)
        response.delete_cookie('synthetic_test_session')
        return response

    def workspace(self) -> Response:
        if request.method == 'OPTIONS':
            return Response(status=200)
        owner = self.owner()
        if owner is None:
            return jsonify(detail='Unauthorised'), 401
        skills = [
            {
                'skill_id': 'service-health',
                'display_name': 'Service health',
                'description': 'Review synthetic service status and recent events.',
                'kind': 'procedural',
                'groups': ['operations', 'operations/health'],
            },
            {
                'skill_id': 'workload-review',
                'display_name': 'Workload review',
                'description': 'Inspect synthetic workload information.',
                'kind': 'procedural',
                'groups': ['operations', 'operations/health'],
            },
            {
                'skill_id': 'summary-report',
                'display_name': 'Summary report',
                'description': 'Prepare a concise synthetic report.',
                'kind': 'output',
                'groups': ['reporting'],
            },
        ]
        return jsonify(
            user_id=owner,
            workspace_id=str(uuid4()),
            version=1,
            skills=skills if owner.endswith('-a') else skills[-1:],
        )

    def create_record(self, owner: str) -> dict:
        identifier = str(uuid4())
        now = datetime.now(UTC).isoformat()
        record = {
            'conversation_id': identifier,
            'title': None,
            'created_at': now,
            'last_activity_at': now,
            'can_continue': True,
            'is_interrupted': False,
            'messages': [],
            'owner': owner,
        }
        self.records[identifier] = record
        return record

    def public(self, record: dict) -> dict:
        return {key: value for key, value in record.items() if key != 'owner'}

    def conversations(self) -> Response:
        if request.method == 'OPTIONS':
            return Response(status=200)
        owner = self.owner()
        if owner is None:
            return jsonify(detail='Unauthorised'), 401
        if request.method == 'POST':
            return jsonify(self.public(self.create_record(owner))), 201
        return jsonify(
            conversations=[
                {
                    key: value
                    for key, value in self.public(record).items()
                    if key != 'messages'
                }
                for record in self.records.values()
                if record['owner'] == owner
            ]
        )

    def conversation(self, identifier: str) -> Response:
        if request.method == 'OPTIONS':
            return Response(status=200)
        record = self.records.get(identifier)
        if record is None or record['owner'] != self.owner():
            return jsonify(detail='Unavailable'), 404
        return jsonify(self.public(record))

    def stream(self, identifier: str) -> Response:
        if request.method == 'OPTIONS':
            return Response(status=200)
        record = self.records.get(identifier)
        if record is None or record['owner'] != self.owner():
            return jsonify(detail='Unavailable'), 404
        if not record['can_continue']:
            return jsonify(error_code='conversation_interrupted'), 409
        text = request.get_json()['text']
        record['can_continue'] = False
        record['title'] = record['title'] or text[:70]
        record['messages'].append({'role': 'user', 'text': text})

        def events():
            complete = False
            answer = '## Synthetic summary\n\nThe response arrived incrementally.\n\n```python\nprint("hello")\n```\n\n| Check | Result |\n| --- | --- |\n| Formatting | Ready |\n\n**This is test data, not a live model response.**'
            chunks = [answer[index : index + 14] for index in range(0, len(answer), 14)]
            try:
                for chunk in chunks:
                    time.sleep(0.35 if 'slow' in text.lower() else 0.03)
                    yield (
                        'data: '
                        + json.dumps(
                            {
                                'partial': True,
                                'content': {
                                    'role': 'model',
                                    'parts': [{'text': chunk}],
                                },
                            }
                        )
                        + '\n\n'
                    )
                yield (
                    'data: '
                    + json.dumps(
                        {
                            'id': str(uuid4()),
                            'partial': False,
                            'content': {'role': 'model', 'parts': [{'text': answer}]},
                        }
                    )
                    + '\n\n'
                )
                record['messages'].append({'role': 'assistant', 'text': answer})
                complete = True
            finally:
                record.update(
                    can_continue=complete,
                    is_interrupted=not complete,
                    last_activity_at=datetime.now(UTC).isoformat(),
                )

        return Response(events(), mimetype='text/event-stream')

    @classmethod
    def run(cls) -> None:
        from werkzeug.serving import run_simple

        run_simple('127.0.0.1', 8000, cls().application, threaded=True)
