import json
import time
from datetime import UTC, datetime
from threading import Condition, Thread
from uuid import uuid4

from flask import Flask, Response, jsonify, request


class BrowserFixtureBackend:
    def __init__(self, gui_origin: str = 'http://127.0.0.1:8050') -> None:
        self.gui_origin = gui_origin
        self.records: dict[str, dict] = {}
        self.jobs: dict[str, dict] = {}
        self.job_changed = Condition()
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
            '/api/v1/conversations/<identifier>/jobs',
            view_func=self.submit_job,
            methods=['POST', 'OPTIONS'],
        )
        self.application.add_url_rule('/api/v1/conversations/jobs/<job_id>', view_func=self.get_job)
        self.application.add_url_rule('/api/v1/conversations/jobs/<job_id>/events', view_func=self.stream_job)
        self.application.add_url_rule('/api/v1/conversations/jobs/<job_id>/stop', view_func=self.stop_job, methods=['POST'])
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
        response.headers['Access-Control-Allow-Origin'] = self.gui_origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Idempotency-Key'
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
            'latest_job': None,
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
                    if key not in ('messages', 'latest_job')
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

    def submit_job(self, identifier: str) -> Response:
        if request.method == 'OPTIONS':
            return Response(status=200)
        record = self.records.get(identifier)
        if record is None or record['owner'] != self.owner():
            return jsonify(detail='Unavailable'), 404
        text = request.get_json()['text']
        key = request.headers.get('Idempotency-Key')
        with self.job_changed:
            earlier = next(
                (job for job in self.jobs.values() if key and job['conversation_id'] == identifier and job['key'] == key),
                None,
            )
            if earlier is not None:
                if earlier['text'] != text:
                    return jsonify(error_code='idempotency_conflict'), 409
                return jsonify(self.public_job(earlier)), 202
            if not record['can_continue']:
                return jsonify(error_code='conversation_busy'), 409
            job = {
                'job_id': str(uuid4()), 'conversation_id': identifier, 'status': 'running',
                'result_text': None, 'events': [], 'key': key, 'text': text,
            }
            self.jobs[job['job_id']] = job
            record['latest_job'] = {'job_id': job['job_id'], 'status': 'running'}
            record['can_continue'] = False
            record['title'] = record['title'] or text[:70]
            record['messages'].append({'role': 'user', 'text': text})
        Thread(target=self.run_job, args=(job, record, text), daemon=True).start()
        return jsonify(self.public_job(job)), 202

    def public_job(self, job: dict) -> dict:
        return {key: job[key] for key in ('job_id', 'conversation_id', 'status', 'result_text')}

    def owned_job(self, job_id: str) -> dict | None:
        job = self.jobs.get(job_id)
        if job is not None and self.records[job['conversation_id']]['owner'] == self.owner():
            return job
        return None

    def get_job(self, job_id: str) -> Response:
        job = self.owned_job(job_id)
        if job is None:
            return jsonify(detail='Unavailable'), 404
        return jsonify(self.public_job(job))

    def stop_job(self, job_id: str) -> Response:
        job = self.owned_job(job_id)
        if job is None:
            return jsonify(detail='Unavailable'), 404
        with self.job_changed:
            if job['status'] == 'running':
                job['status'] = 'stopping'
                self.records[job['conversation_id']]['latest_job']['status'] = 'stopping'
            return jsonify(self.public_job(job))

    def stream_job(self, job_id: str) -> Response:
        job = self.owned_job(job_id)
        if job is None:
            return jsonify(detail='Unavailable'), 404
        after = request.args.get('after', 0, type=int)

        def replay():
            cursor = after
            while True:
                with self.job_changed:
                    self.job_changed.wait_for(
                        lambda: len(job['events']) > cursor or job['status'] in ('succeeded', 'cancelled', 'failed')
                    )
                    if len(job['events']) <= cursor:
                        return
                    frame = job['events'][cursor]
                    cursor += 1
                yield f'id: {cursor}\n{frame}'

        return Response(replay(), mimetype='text/event-stream')

    def run_job(self, job: dict, record: dict, text: str) -> None:
        """
        Produce one synthetic job independently of its browser stream.
        """
        def events():
            answer = '## Synthetic summary\n\nThe response arrived incrementally.\n\n```python\nprint("hello")\n```\n\n| Check | Result |\n| --- | --- |\n| Formatting | Ready |\n\n**This is test data, not a live model response.**'
            chunks = [answer[index : index + 14] for index in range(0, len(answer), 14)]
            if record['owner'].endswith('-a'):
                for part in (
                    {'functionCall': {'name': 'load_skills', 'id': 'load'}},
                    {
                        'functionResponse': {
                            'name': 'load_skills',
                            'id': 'load',
                            'response': {
                                'status': 'loaded',
                                'loaded_skills': [
                                    {
                                        'name': 'service-health',
                                        'required_capability_names': [
                                            'kubernetes.pods.status.read'
                                        ],
                                    }
                                ],
                            },
                        }
                    },
                    {
                        'functionCall': {
                            'name': 'discover_capabilities',
                            'id': 'discovery',
                        }
                    },
                    {
                        'functionResponse': {
                            'name': 'discover_capabilities',
                            'id': 'discovery',
                            'response': {
                                'status': 'available',
                                'capabilities': [
                                    {
                                        'name': 'kubernetes.pods.status.read',
                                        'available': True,
                                        'description': 'Review synthetic workload readiness.',
                                    }
                                ],
                            },
                        }
                    },
                    {
                        'functionCall': {
                            'name': 'execute_capability',
                            'id': 'check',
                            'args': {
                                'capability_name': 'kubernetes.pods.status.read',
                            },
                        }
                    },
                    {
                        'functionResponse': {
                            'name': 'execute_capability',
                            'id': 'check',
                            'response': {'status': 'success'},
                        }
                    },
                ):
                    yield (
                        'data: '
                        + json.dumps(
                            {
                                'content': {
                                    'role': 'model'
                                    if 'functionCall' in part
                                    else 'user',
                                    'parts': [part],
                                }
                            }
                        )
                        + '\n\n'
                    )
                    time.sleep(2 if 'slow' in text.lower() else 0.08)
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
            return answer

        frames = events()
        status = 'failed'
        try:
            while True:
                frame = next(frames)
                with self.job_changed:
                    if job['status'] == 'stopping':
                        status = 'cancelled'
                        break
                    job['events'].append(frame)
                    self.job_changed.notify_all()
        except StopIteration as completed:
            with self.job_changed:
                if job['status'] == 'stopping':
                    status = 'cancelled'
                else:
                    status = 'succeeded'
                    job['result_text'] = completed.value
                    record['messages'].append({'role': 'assistant', 'text': completed.value})
        finally:
            frames.close()
            with self.job_changed:
                job['status'] = status
                record['latest_job']['status'] = status
                record.update(can_continue=True, last_activity_at=datetime.now(UTC).isoformat())
                self.job_changed.notify_all()

    @classmethod
    def run(cls) -> None:
        from werkzeug.serving import run_simple

        run_simple('127.0.0.1', 8000, cls().application, threaded=True)
