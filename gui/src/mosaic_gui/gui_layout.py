import dash_bootstrap_components as dbc
from dash import dcc
from dash import html

from .gui_configuration import GuiConfiguration


class GuiLayout:
    def __init__(self, configuration: GuiConfiguration) -> None:
        """
        Bind the Bootstrap workspace shell to safe public GUI configuration.

        :param configuration: Backend origin and optional private branding dimensions.
        """
        self._configuration = configuration

    def create_layout(self) -> html.Div:
        """
        Create sign-in and workspace controls; browser-only code owns interaction state.

        :return: Accessible Bootstrap-based MOSAIC page without stored credentials.
        """
        logo = html.Img(src='/assets/tangram.svg', alt='', className='mosaic-symbol')
        organisation_logo = (
            []
            if self._configuration.organisation_logo_path is None
            else [
                html.Img(
                    src='/branding/logo.png',
                    alt='Organisation logo',
                    className='organisation-logo',
                    style={
                        'maxWidth': f'{self._configuration.organisation_logo_width}px',
                        'maxHeight': f'{self._configuration.organisation_logo_height}px',
                    },
                )
            ]
        )
        return html.Div(
            [
                html.Header(
                    [
                        html.Div(
                            [
                                *organisation_logo,
                                *(
                                    [
                                        html.Span(
                                            className='brand-divider',
                                            **{'aria-hidden': 'true'},
                                        )
                                    ]
                                    if organisation_logo
                                    else []
                                ),
                                logo,
                                html.Div(
                                    [
                                        html.Span('MOSAIC', className='wordmark'),
                                        html.Span(
                                            'Agent workspace', className='brand-caption'
                                        ),
                                    ]
                                ),
                            ],
                            className='brand',
                        ),
                        html.Div(
                            [
                                dbc.Badge(
                                    'PILOT', color='light', className='pilot-badge'
                                ),
                                html.Div(id='user-label', className='user-label'),
                                dbc.Button(
                                    'Sign out',
                                    id='sign-out',
                                    color='link',
                                    className='sign-out-button',
                                    style={'display': 'none'},
                                ),
                            ],
                            className='header-actions',
                        ),
                    ],
                    className='workspace-header',
                ),
                html.Nav(
                    [
                        html.Button('Chat', id='show-chat', type='button'),
                        html.Button('Skills', id='show-skill-browser', type='button'),
                    ],
                    id='workspace-navigation',
                    className='workspace-navigation',
                    style={'display': 'none'},
                    **{'aria-label': 'Workspace'},
                ),
                html.Main(
                    [
                        html.Div(
                            [
                                html.Section(
                                    [
                                        html.H1(
                                            [
                                                'Intelligence,',
                                                html.Br(),
                                                html.Span('orchestrated.'),
                                            ]
                                        ),
                                    ],
                                    className='login-introduction',
                                ),
                                dbc.Card(
                                    dbc.CardBody(
                                        [
                                            html.Img(
                                                src='/assets/tangram.svg',
                                                alt='',
                                                className='sign-in-symbol',
                                            ),
                                            html.H2('Sign in to your workspace'),
                                            html.P(
                                                'Use the access token provided by your administrator.',
                                                className='text-muted',
                                            ),
                                            dbc.Form(
                                                [
                                                    dbc.Label(
                                                        'Access token',
                                                        html_for='pilot-token',
                                                    ),
                                                    html.Div(id='token-input-slot'),
                                                    dbc.Button(
                                                        'Sign in',
                                                        id='sign-in',
                                                        color='primary',
                                                        className='w-100 sign-in-button',
                                                        type='button',
                                                    ),
                                                ],
                                                id='sign-in-form',
                                            ),
                                            dbc.Alert(
                                                id='sign-in-error',
                                                color='danger',
                                                is_open=False,
                                                className='mt-3',
                                            ),
                                            html.P(
                                                'Your token is exchanged for a protected browser cookie.',
                                                className='sign-in-note',
                                            ),
                                            html.P(
                                                'Built on Ada',
                                                className='foundation-credit',
                                            ),
                                        ]
                                    ),
                                    className='sign-in-card',
                                ),
                            ],
                            id='login-screen',
                            className='login-screen',
                        ),
                        html.Div(
                            [
                                html.Aside(
                                    [
                                        html.Div(
                                            [
                                                html.H2('Conversations'),
                                                dbc.Button(
                                                    'Hide',
                                                    id='history-toggle',
                                                    color='link',
                                                    size='sm',
                                                    title='Hide conversations',
                                                ),
                                            ],
                                            className='panel-heading',
                                        ),
                                        dbc.Button(
                                            '+ New conversation',
                                            id='new-conversation',
                                            color='primary',
                                            outline=True,
                                            className='new-conversation-button',
                                        ),
                                        html.Div(
                                            id='conversation-list',
                                            className='conversation-list',
                                        ),
                                        html.Div(
                                            'History stays with your account.',
                                            className='panel-footer',
                                        ),
                                    ],
                                    id='history-panel',
                                    className='history-panel',
                                ),
                                html.Div(
                                    id='history-resizer',
                                    className='panel-resizer',
                                    role='separator',
                                    tabIndex=0,
                                    **{
                                        'aria-label': 'Resize conversations panel',
                                        'aria-orientation': 'vertical',
                                        'aria-valuemin': 200,
                                        'aria-valuemax': 380,
                                        'aria-valuenow': 250,
                                    },
                                ),
                                html.Section(
                                    [
                                        html.Div(
                                            [
                                                html.Div(
                                                    [
                                                        dbc.Button(
                                                            [
                                                                html.Span(
                                                                    '▤',
                                                                    **{
                                                                        'aria-hidden': 'true'
                                                                    },
                                                                ),
                                                                html.Span(
                                                                    'Show Conversations',
                                                                    className='visually-hidden',
                                                                ),
                                                            ],
                                                            id='history-show',
                                                            className='panel-show',
                                                            title='Show Conversations',
                                                            color='link',
                                                            size='sm',
                                                            style={'display': 'none'},
                                                        ),
                                                        html.H1(
                                                            'New conversation',
                                                            id='conversation-title',
                                                        ),
                                                    ],
                                                    className='conversation-heading',
                                                ),
                                                html.Div(
                                                    [
                                                        dbc.Badge(
                                                            'Ready',
                                                            id='conversation-state',
                                                            color='success',
                                                            className='state-badge',
                                                        ),
                                                        dbc.Button(
                                                            [
                                                                html.Span(
                                                                    '◈',
                                                                    **{
                                                                        'aria-hidden': 'true'
                                                                    },
                                                                ),
                                                                html.Span(
                                                                    'Show Current Skills',
                                                                    className='visually-hidden',
                                                                ),
                                                            ],
                                                            id='skills-show',
                                                            className='panel-show',
                                                            title='Show Current Skills',
                                                            color='link',
                                                            size='sm',
                                                            style={'display': 'none'},
                                                        ),
                                                    ],
                                                    className='conversation-tools',
                                                ),
                                            ],
                                            className='conversation-toolbar',
                                        ),
                                        dbc.Alert(
                                            id='workspace-alert',
                                            color='warning',
                                            is_open=False,
                                            className='workspace-alert',
                                        ),
                                        html.Div(
                                            [
                                                html.Span(
                                                    className='spinner-border spinner-border-sm',
                                                    **{'aria-hidden': 'true'},
                                                ),
                                                html.Div(
                                                    [
                                                        html.Div(
                                                            id='invocation-skills',
                                                            className='invocation-skills',
                                                        ),
                                                        html.Div(
                                                            id='invocation-stage',
                                                            role='status',
                                                            **{'aria-live': 'polite'},
                                                        ),
                                                    ],
                                                    className='invocation-description',
                                                ),
                                                html.Span(
                                                    id='invocation-elapsed',
                                                    className='invocation-elapsed',
                                                    title='Elapsed request time; not a backend heartbeat.',
                                                    **{'aria-live': 'off'},
                                                ),
                                            ],
                                            id='invocation-activity',
                                            className='invocation-activity',
                                            style={'display': 'none'},
                                        ),
                                        html.Div(
                                            id='messages',
                                            className='messages',
                                            **{
                                                'aria-live': 'polite',
                                                'aria-relevant': 'additions text',
                                            },
                                        ),
                                        html.Div(
                                            [
                                                dbc.Textarea(
                                                    id='message-input',
                                                    placeholder='What would you like to work on?',
                                                    rows=2,
                                                    className='message-input',
                                                ),
                                                html.Div(
                                                    [
                                                        html.Span(
                                                            'Enter to send · Shift+Enter for a new line',
                                                            className='composer-hint',
                                                        ),
                                                        html.Div(
                                                            [
                                                                dbc.Button(
                                                                    'Stop',
                                                                    id='stop-stream',
                                                                    color='danger',
                                                                    outline=True,
                                                                    size='sm',
                                                                    style={
                                                                        'display': 'none'
                                                                    },
                                                                ),
                                                                dbc.Button(
                                                                    'Send',
                                                                    id='send-message',
                                                                    color='primary',
                                                                ),
                                                            ],
                                                            className='composer-actions',
                                                        ),
                                                    ],
                                                    className='composer-bottom',
                                                ),
                                                html.P(
                                                    'MOSAIC can make mistakes. Validate important information.',
                                                    className='composer-disclaimer',
                                                ),
                                            ],
                                            id='composer',
                                            className='composer',
                                        ),
                                    ],
                                    className='conversation-panel',
                                ),
                                html.Div(
                                    id='skills-resizer',
                                    className='panel-resizer',
                                    role='separator',
                                    tabIndex=0,
                                    **{
                                        'aria-label': 'Resize Skills panel',
                                        'aria-orientation': 'vertical',
                                        'aria-valuemin': 220,
                                        'aria-valuemax': 420,
                                        'aria-valuenow': 290,
                                    },
                                ),
                                html.Aside(
                                    [
                                        html.Div(
                                            [
                                                html.H2('Current Skills'),
                                                dbc.Button(
                                                    'Hide',
                                                    id='skills-toggle',
                                                    color='link',
                                                    size='sm',
                                                    title='Hide Current Skills',
                                                ),
                                            ],
                                            className='panel-heading',
                                        ),
                                        html.Div(
                                            html.Span(id='skill-count'),
                                            className='skill-summary',
                                        ),
                                        html.Div(
                                            id='skills-list', className='skills-list'
                                        ),
                                        html.Div(
                                            'Skill changes apply to the next Goal.',
                                            className='panel-footer',
                                        ),
                                    ],
                                    id='skills-panel',
                                    className='skills-panel',
                                ),
                            ],
                            id='workspace-screen',
                            className='workspace-screen',
                            style={'display': 'none'},
                        ),
                        self._skill_browser(),
                    ],
                    id='workspace-main',
                    className='page-main',
                ),
                dcc.Store(id='conversation-row-ids', storage_type='memory'),
                dcc.Store(id='conversation-sidebar-view', storage_type='memory'),
                dcc.Store(id='conversation-action-result', storage_type='memory'),
                dcc.Store(id='skill-catalogue-view', storage_type='memory'),
                dcc.Store(id='skill-selection-view', storage_type='memory'),
                dcc.Store(id='saved-skill-view', storage_type='memory'),
                dcc.Store(id='skill-action-result', storage_type='memory'),
            ],
            id='mosaic-root',
            **{'data-backend-url': self._configuration.backend_url},
        )

    def _skill_browser(self) -> html.Section:
        """
        Build the paged Skill browser and persistent selection panel.

        :return: Skills view for signed-in workspace users.
        """
        return html.Section(
            [
                html.H1('Skills Marketplace'),
                html.P(
                    'Choose the Skills available to your workspace. Changes apply to the next Goal.',
                    className='browser-description',
                ),
                html.Div(
                    [
                        html.Div(
                            [
                                html.Label(
                                    'Search Skills',
                                    htmlFor='skill-search',
                                    className='visually-hidden',
                                ),
                                dcc.Input(
                                    id='skill-search',
                                    type='search',
                                    value='',
                                    debounce=0.25,
                                    maxLength=200,
                                    placeholder='Search Skills',
                                    className='form-control form-control-sm',
                                ),
                                html.Div(
                                    id='skill-browser-path', className='browser-path'
                                ),
                            ],
                            className='browser-toolbar',
                        ),
                        dbc.Alert(
                            id='skill-editor-alert',
                            color='warning',
                            is_open=False,
                            className='m-2',
                        ),
                        html.Div(
                            [
                                html.Div(
                                    id='skill-browser-columns',
                                    className='browser-columns',
                                ),
                                html.Aside(
                                    [
                                        html.H2(
                                            'Current Skills',
                                            id='current-skills-heading',
                                        ),
                                        html.Div(
                                            id='current-skills',
                                            className='browser-list',
                                        ),
                                    ],
                                    className='browser-column selected-panel',
                                    **{'aria-labelledby': 'current-skills-heading'},
                                ),
                            ],
                            className='browser-content',
                        ),
                        html.Div(
                            [
                                html.Strong(id='skill-selection-count', role='status'),
                                html.Span(
                                    id='skill-save-status',
                                    className='browser-status me-auto',
                                    role='status',
                                ),
                                dbc.Button(
                                    'Discard changes',
                                    id='cancel-skills',
                                    color='link',
                                    size='sm',
                                ),
                                dbc.Button(
                                    'Save Skills',
                                    id='save-skills',
                                    color='primary',
                                    size='sm',
                                ),
                            ],
                            className='browser-footer',
                        ),
                    ],
                    className='skill-browser',
                ),
            ],
            id='skill-editor',
            className='skill-browser-screen',
            style={'display': 'none'},
        )
