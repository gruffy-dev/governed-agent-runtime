"""Apply Marketplace events in Dash and describe the API work the browser needs."""

from dash import Input, Output, State, no_update

from .skill_views import render_catalogue, render_selection, workspace_selection


def register_skill_editor(application):
    application.callback(
        Output('skill-editor-state', 'data'),
        Input('skill-editor-event', 'data'),
        State('skill-editor-state', 'data'),
        prevent_initial_call=True,
    )(update_editor)
    application.callback(
        Output('skill-browser-path', 'children'),
        Output('skill-browser-columns', 'children'),
        Output('skill-browser-columns', 'className'),
        Output('current-skills', 'children'),
        Output('skill-selection-count', 'children'),
        Output('skill-save-status', 'children'),
        Output('skill-editor-alert', 'is_open'),
        Output('skill-editor-alert', 'children'),
        Output('skill-search', 'disabled'),
        Output('save-skills', 'disabled'),
        Output('cancel-skills', 'disabled'),
        Input('skill-editor-state', 'data'),
        Input('skill-workspace-busy', 'data'),
    )(render_editor)
    application.clientside_callback(
        """
        function(state) {
            window.mosaicSkillState?.(state);
            return window.dash_clientside.no_update;
        }
        """,
        Output('skill-action-result', 'data', allow_duplicate=True),
        Input('skill-editor-state', 'data'),
        prevent_initial_call=True,
    )


def update_editor(event, previous):
    """Update an editor belonging to one browser, without server-side session state."""
    if not event:
        return no_update
    sequence = event['sequence']
    action = event['action']
    if action == 'reset':
        return {'sequence': sequence}
    if action == 'open' and not (previous or {}).get('ready'):
        state = {
            'ready': False,
            'version': None,
            'domain': None,
            'function': None,
            'query': '',
            'level': 'domains',
            'pages': {},
            'selected': {},
            'saved': {},
            'members': {},
            'unverified': [],
            'status': '',
            'error': '',
            'request': {'kind': 'workspace', 'id': sequence},
        }
    elif 'ready' in (previous or {}):
        state = previous
        if action == 'result':
            _apply_result(state, event['value'], sequence)
        elif state['ready']:
            _apply_action(state, action, event.get('value'), sequence)
        _check_memberships(state, sequence)
    else:
        return {'sequence': sequence}
    state['sequence'] = sequence
    return state


def _dirty(state):
    return state['selected'].keys() != state['saved'].keys()


def _catalogue_request(state, level, sequence, more=False):
    params = {}
    if level in ('functions', 'skills'):
        params['domain'] = state['domain']
    if level == 'skills':
        params['function'] = state['function']
    if level == 'search':
        params['q'] = state['query']
    if more:
        offset = state['pages'].get(level, {}).get('next_offset')
        if offset is None:
            return
        params['offset'] = offset
    state['request'] = {
        'id': sequence,
        'kind': 'catalogue',
        'level': level,
        'params': params,
    }


def _skill_membership(skill, domain, function):
    if skill.get('withdrawn'):
        return False
    groups = skill['groups']
    if function != '~':
        return f'{domain}/{function}' in groups
    if domain == '~':
        return not groups
    return domain in groups and not any(
        group.startswith(f'{domain}/') for group in groups
    )


def _function_state(state, name):
    domain = state['domain']
    members = state['members'].get(f'{domain}/{name}')
    if members is None:
        return (
            'mixed'
            if any(
                _skill_membership(skill, domain, name)
                for skill in state['selected'].values()
            )
            else 'false'
        )
    selected = sum(skill['skill_id'] in state['selected'] for skill in members)
    if not selected:
        return 'false'
    return 'true' if selected == len(members) else 'mixed'


def _check_memberships(state, sequence):
    if not state['ready'] or state['request'] or state['query'] or not state['domain']:
        return
    for name in state['pages'].get('functions', {}).get('items', []):
        key = f'{state["domain"]}/{name}'
        if (
            key not in state['members']
            and key not in state['unverified']
            and _function_state(state, name) == 'mixed'
        ):
            _request_members(state, name, sequence, 'check')
            return


def _request_members(state, name, sequence, kind):
    state['request'] = {
        'id': sequence,
        'kind': kind,
        'name': name,
        'params': {'domain': state['domain'], 'function': name},
        'page': state['pages'].get('skills') if name == state['function'] else None,
        'clear': _function_state(state, name) == 'true',
    }


def _toggle_members(state, name, members, clear):
    for skill in members:
        skill_id = skill['skill_id']
        if clear:
            state['selected'].pop(skill_id, None)
        else:
            state['selected'][skill_id] = skill
    if name == state['function']:
        state['pages']['skills'] = {'items': members, 'next_offset': None}
    state['status'] = ''


def _apply_action(state, action, value, sequence):
    request = state['request']
    if request and request['kind'] in ('save', 'conflict'):
        return
    if action == 'hide':
        if request and request['kind'] == 'bulk':
            state['request'] = None
        return
    if action == 'skill-search':
        state['query'] = (value or '').strip()[:200]
        state['pages'].pop('search', None)
        state['request'] = None
        level = (
            'search'
            if state['query']
            else 'skills'
            if state['function']
            else 'functions'
            if state['domain']
            else 'domains'
        )
        if level not in state['pages']:
            _catalogue_request(state, level, sequence)
        return
    if action == 'cancel-skills':
        state.update(selected=state['saved'].copy(), status='', error='')
        if request and request['kind'] == 'bulk':
            state['request'] = None
        return
    if action == 'save-skills':
        if _dirty(state) and state['version'] is not None:
            state['error'] = ''
            state['request'] = {
                'id': sequence,
                'kind': 'save',
                'body': {
                    'expected_version': state['version'],
                    'skill_ids': list(state['selected']),
                },
            }
        return

    prefix, _, target = action.removeprefix('skill-').partition('-')
    level, _, name = target.partition('-')
    if prefix in ('more', 'retry') and level in (
        'domains',
        'functions',
        'skills',
        'search',
    ):
        _catalogue_request(state, level, sequence, more=prefix == 'more')
    elif prefix == 'back' and level in ('domains', 'functions'):
        state['level'] = level
        if request and request['kind'] == 'bulk':
            state['request'] = None
    elif prefix == 'path' and name in state['pages'].get(level, {}).get('items', []):
        if level == 'domains':
            state.update(domain=name, function=None, level='functions')
            state['pages'].pop('functions', None)
        else:
            state.update(function=name, level='skills')
        state['pages'].pop('skills', None)
        _catalogue_request(state, state['level'], sequence)
    elif prefix == 'function':
        if level == 'mobile':
            name = state['function']
        if (
            state['query']
            or state['version'] is None
            or name not in state['pages'].get('functions', {}).get('items', [])
        ):
            return
        if request and request['kind'] == 'bulk':
            return
        state['error'] = ''
        key = f'{state["domain"]}/{name}'
        if key in state['members']:
            _toggle_members(
                state,
                name,
                state['members'][key],
                _function_state(state, name) == 'true',
            )
        else:
            _request_members(state, name, sequence, 'bulk')
    elif prefix in ('option', 'remove'):
        if target in state['selected']:
            del state['selected'][target]
        elif prefix == 'option':
            level = 'search' if state['query'] else 'skills'
            skill = next(
                (
                    skill
                    for skill in state['pages'].get(level, {}).get('items', [])
                    if skill['skill_id'] == target
                ),
                None,
            )
            if skill:
                state['selected'][target] = skill
        if request and request['kind'] == 'bulk':
            state['request'] = None
        state['status'] = ''


def _apply_result(state, result, sequence):
    request = state['request']
    if not request or request['id'] != result['id']:
        return
    state['request'] = None
    kind = request['kind']
    if error := result.get('error'):
        if kind == 'save' and result.get('status') == 409:
            state['request'] = {
                'id': sequence,
                'kind': 'conflict',
                'reference': result.get('reference'),
            }
        elif kind == 'check':
            state['unverified'].append(
                f'{request["params"]["domain"]}/{request["name"]}'
            )
        else:
            state['error'] = error
        return

    data = result['data']
    if kind in ('workspace', 'save', 'conflict'):
        saved = {skill['skill_id']: skill for skill in workspace_selection(data)}
        state.update(version=data['version'], saved=saved, ready=True)
        if kind == 'conflict':
            state['selected'] = {
                skill_id: saved.get(skill_id, skill)
                for skill_id, skill in state['selected'].items()
                if skill_id in saved or not skill.get('withdrawn')
            }
            names = (
                ', '.join(
                    skill['display_name']
                    + (' (withdrawn)' if skill.get('withdrawn') else '')
                    for skill in saved.values()
                )
                or 'None'
            )
            state['error'] = (
                'This workspace is no longer available. Cancel and contact your administrator.'
                if state['version'] is None
                else f'Skills changed elsewhere. Currently saved: {names}. Your draft is still selected. Review it before saving again.'
            )
            if request.get('reference'):
                state['error'] += f' Reference: {request["reference"]}'
        else:
            state['selected'] = saved.copy()
            if kind == 'save':
                state['status'] = 'Skills saved'
            else:
                if state['version'] is None:
                    state['error'] = (
                        'This account has no workspace to edit. Contact your administrator.'
                    )
                _catalogue_request(state, 'domains', sequence)
    elif kind == 'catalogue':
        level = request['level']
        previous = (
            state['pages'].get(level, {}).get('items', [])
            if 'offset' in request['params']
            else []
        )
        state['pages'][level] = {
            'items': [*previous, *data['items']],
            'next_offset': data['next_offset'],
        }
        if level == 'skills' and data['next_offset'] is None:
            state['members'][f'{state["domain"]}/{state["function"]}'] = state['pages'][
                level
            ]['items']
    else:
        name = request['name']
        state['members'][f'{request["params"]["domain"]}/{name}'] = data
        if kind == 'bulk':
            _toggle_members(state, name, data, request['clear'])


def render_editor(state, browser_busy):
    if not state or 'ready' not in state:
        return '', [], 'browser-columns', [], '', '', False, '', True, True, True
    request = state['request'] or {}
    catalogue = request.get('kind') == 'catalogue'
    bulk = request.get('kind') == 'bulk'
    busy = browser_busy or request.get('kind') in ('save', 'conflict')
    path, columns, class_name = render_catalogue(
        {
            **state,
            'loading': request['level'] if catalogue else None,
            'bulk_function': request['name'] if bulk else None,
            'function_disabled': busy
            or state['version'] is None
            or bulk
            or (catalogue and request['level'] == 'functions'),
            'function_states': {
                name: _function_state(state, name)
                for name in state['pages'].get('functions', {}).get('items', [])
            },
        }
    )
    selected = list(state['selected'].values())
    count = sum(not skill.get('withdrawn') for skill in selected)
    dirty = _dirty(state)
    return (
        path,
        columns,
        class_name,
        render_selection(selected, editable=True) if state['ready'] else [],
        f'{count} selected' if state['ready'] else '',
        state['status'] or ('Unsaved changes' if dirty else ''),
        bool(state['error']),
        state['error'],
        busy or not state['ready'],
        busy or not dirty or state['version'] is None,
        busy or not dirty,
    )
