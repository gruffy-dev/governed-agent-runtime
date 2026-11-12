from dash import ALL, Input, Output, html


def register_skill_callbacks(application):
    """Render Skills in Dash and route browser-owned actions through component inputs."""
    application.callback(
        Output('skill-browser-path', 'children'),
        Output('skill-browser-columns', 'children'),
        Output('skill-browser-columns', 'className'),
        Input('skill-catalogue-view', 'data'),
    )(render_catalogue)
    application.callback(
        Output('current-skills', 'children'),
        Input('skill-selection-view', 'data'),
    )(lambda skills: render_selection(skills, editable=True))
    application.callback(
        Output('skills-list', 'children'),
        Input('saved-skill-view', 'data'),
    )(render_selection)
    application.clientside_callback(
        """
        function(clicks, chat, skills, save, discard) {
            const context = window.dash_clientside.callback_context;
            const id = context.triggered_id;
            const noUpdate = window.dash_clientside.no_update;
            if (!id) return noUpdate;
            if (typeof id === "object") {
                const control = context.inputs_list[0].find(input => input.id.action === id.action);
                if (control?.value > 0) window.mosaicSkillAction?.(id.action);
            } else if (context.triggered[0]?.value > 0) {
                window.mosaicSkillAction?.(id);
            }
            return noUpdate;
        }
        """,
        Output('skill-action-result', 'data'),
        Input({'type': 'skill-control', 'action': ALL}, 'n_clicks'),
        Input('show-chat', 'n_clicks'),
        Input('show-skill-browser', 'n_clicks'),
        Input('save-skills', 'n_clicks'),
        Input('cancel-skills', 'n_clicks'),
        prevent_initial_call=True,
    )
    application.clientside_callback(
        '''
        function(query) {
            window.mosaicSkillAction?.("skill-search", query);
            return window.dash_clientside.no_update;
        }
        ''',
        Output('skill-action-result', 'data', allow_duplicate=True),
        Input('skill-search', 'value'),
        prevent_initial_call=True,
    )


def _button(action, children=None, **properties):
    return html.Button(
        children,
        id={'type': 'skill-control', 'action': action},
        type='button',
        n_clicks=0,
        **properties,
    )


def _label(name, fallback):
    label = name.replace('-', ' ')
    return fallback if name == '~' else label[:1].upper() + label[1:]


def _details(skill, expanded=False):
    return html.Details(
        [
            html.Summary(skill['display_name']),
            html.P(skill['description'], className='skill-description'),
        ],
        className='skill-details',
        open=expanded,
    )


def _function_checkbox(name, view, mobile=False):
    return _button(
        'skill-function-mobile' if mobile else 'skill-function-toggle-' + name,
        role='checkbox',
        className='skill-option',
        title='Select or clear all available Skills in this function',
        **{
            'aria-checked': view['function_states'].get(name, 'false'),
            'aria-label': 'All available Skills in ' + _label(name, 'General'),
            'aria-disabled': view['function_disabled'],
            'aria-busy': view['bulk_function'] == name,
        },
    )


def _catalogue_row(level, item, view):
    if level in ('domains', 'functions'):
        path = _button(
            'skill-path-' + level + '-' + item,
            [
                _label(item, 'Ungrouped' if level == 'domains' else 'General'),
                html.Span('›', **{'aria-hidden': 'true'}),
            ],
            className='browser-row',
            **{
                'aria-pressed': str(
                    item == view['domain' if level == 'domains' else 'function']
                ).lower()
            },
        )
        if level == 'domains':
            return path
        return html.Div(
            [_function_checkbox(item, view), path], className='skill-function-row'
        )

    skill_id = item['skill_id']
    children = [
        _button(
            'skill-option-' + skill_id,
            className='skill-option',
            **{
                'aria-label': 'Select ' + item['display_name'],
                'aria-pressed': str(skill_id in view['selected']).lower(),
            },
        ),
        _details(item, expanded=True),
    ]
    if level == 'search':
        groups = item['groups']
        path = ' · '.join(group for group in groups if '/' in group) or ' · '.join(
            groups
        )
        if path:
            children.append(html.Small(path.replace('/', ' › ').replace('-', ' ')))
    return html.Div(children, className='browser-skill', key=f'{level}-{skill_id}')


def _catalogue_column(level, title, view):
    page = view['pages'].get(level)
    items = [
        _catalogue_row(level, item, view) for item in (page or {}).get('items', [])
    ]
    loading = view['loading']
    if loading == level:
        items.append(html.P('Loading…', className='browser-empty', role='status'))
    elif not items:
        parent = {'functions': view['domain'], 'skills': view['function']}.get(
            level, True
        )
        if not view['ready']:
            message = 'Loading workspace…'
        elif page:
            message = 'No matching Skills.'
        elif parent:
            message = 'No results loaded.'
        else:
            message = (
                'Choose a domain.' if level == 'functions' else 'Choose a function.'
            )
        items.append(html.P(message, className='browser-empty'))
        if view['ready'] and parent and not page:
            items.append(
                _button(
                    'skill-retry-' + level, 'Try again', className='btn btn-link btn-sm'
                )
            )
    if page and page.get('next_offset') is not None:
        items.append(
            _button(
                'skill-more-' + level,
                'Load more',
                className='btn btn-link btn-sm',
                disabled=loading is not None,
            )
        )
    if level == 'skills':
        if view['bulk_function']:
            items.insert(
                0,
                html.P(
                    'Loading all Skills in this function…',
                    className='browser-empty',
                    role='status',
                ),
            )
        name = view['function']
        if name:
            items.insert(
                0,
                html.Div(
                    [
                        _function_checkbox(name, view, mobile=True),
                        html.Span(_label(name, 'General')),
                    ],
                    className='skill-function-row skill-function-mobile',
                ),
            )
    active = ' current-column' if view['query'] or level == view['level'] else ''
    return html.Section(
        [html.H2(title), html.Div(items, className='browser-list')],
        className='browser-column' + active,
    )


def render_catalogue(view):
    """Return the catalogue path and columns for a browser-provided view."""
    if view is None:
        return '', [], 'browser-columns'
    if view['query']:
        return (
            'Across all domains',
            [_catalogue_column('search', 'Search results', view)],
            'browser-columns search-results',
        )
    path = [_button('skill-back-domains', 'Domains', className='btn btn-link')]
    if view['domain']:
        path.extend(
            [
                ' › ',
                _button(
                    'skill-back-functions',
                    _label(view['domain'], 'Ungrouped'),
                    className='btn btn-link',
                ),
            ]
        )
    if view['function']:
        path.extend([' › ', _label(view['function'], 'General')])
    levels = (('domains', 'Domain'), ('functions', 'Function'), ('skills', 'Skill'))
    return (
        path,
        [_catalogue_column(level, title, view) for level, title in levels],
        'browser-columns',
    )


def _skill_group(skill):
    groups = sorted(skill['groups'])
    path = next(
        (group for group in groups if '/' in group), groups[0] if groups else '~'
    )
    domain, _, function = path.partition('/')
    return _label(domain, 'Ungrouped'), _label(function or '~', 'General')


def _selection_card(skill, editable):
    name = skill['display_name']
    withdrawn = skill.get('withdrawn', False)
    children = [
        html.Strong(name, className='withdrawn-skill-name')
        if withdrawn
        else _details(skill)
    ]
    if editable:
        children.append(
            _button(
                'skill-remove-' + skill['skill_id'],
                '×',
                className='btn btn-link',
                **{'aria-label': 'Remove ' + name},
            )
        )
    return html.Div(
        children,
        className='selected-item withdrawn-item' if withdrawn else 'selected-item',
        key=skill['skill_id'],
    )


def render_selection(skills, editable=False):
    """Render the selected and withdrawn Skills using native Dash components."""
    if skills is None:
        return []
    if not skills:
        if editable:
            return 'No Skills selected.'
        return html.P(
            'No Skills are selected. Open the Skills tab to choose them.',
            className='browser-empty',
        )

    grouped = sorted(
        (
            (_skill_group(skill), skill)
            for skill in skills
            if not skill.get('withdrawn')
        ),
        key=lambda item: (
            *map(str.casefold, item[0]),
            item[1]['display_name'].casefold(),
            item[1]['skill_id'],
        ),
    )
    items = []
    last_domain = last_function = None
    for (domain, function), skill in grouped:
        if domain != last_domain:
            items.append(html.H3(domain, className='selected-domain'))
            last_domain, last_function = domain, None
        if function != last_function:
            items.append(html.H4(function, className='selected-category'))
            last_function = function
        items.append(_selection_card(skill, editable))

    withdrawn = sorted(
        (skill for skill in skills if skill.get('withdrawn')),
        key=lambda skill: (skill['display_name'].casefold(), skill['skill_id']),
    )
    if withdrawn:
        notice = [
            html.H3('Withdrawn', className='withdrawn-heading'),
            html.P(
                'These Skills are no longer in the catalogue and won’t be used in new Goals.',
                className='withdrawn-note',
            ),
        ]
        if editable:
            notice.append(
                html.P(
                    ['Remove them and select ', html.Strong('Save Skills'), '.'],
                    className='withdrawn-note',
                )
            )
        items.append(
            html.Section(
                [*notice, *(_selection_card(skill, editable) for skill in withdrawn)],
                className='withdrawn-panel',
            )
        )
    return items
