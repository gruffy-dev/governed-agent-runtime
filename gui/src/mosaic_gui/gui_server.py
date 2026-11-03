from flask import Flask
from gunicorn.app.base import BaseApplication

from .gui_configuration import GuiConfiguration


class GuiServer(BaseApplication):
    def __init__(self, application: Flask, configuration: GuiConfiguration) -> None:
        """
        Bind the GUI application to a supervised Gunicorn listener.

        :param application: Standalone Flask application owned by Dash.
        :param configuration: Validated listener configuration.
        """
        self.application = application
        self.configuration = configuration
        super().__init__()

    def load_config(self) -> None:
        """
        Apply explicit listener settings independently of ambient Gunicorn arguments.
        """
        host = self.configuration.host
        if ':' in host and not host.startswith('['):
            host = f'[{host}]'
        self.cfg.set('bind', f'{host}:{self.configuration.port}')
        self.cfg.set('worker_class', 'gthread')
        self.cfg.set('workers', 1)
        self.cfg.set('threads', 4)
        if self.configuration.scheme == 'https':
            self.cfg.set('certfile', str(self.configuration.tls_cert_file.resolve()))
            self.cfg.set('keyfile', str(self.configuration.tls_key_file.resolve()))

    def load(self) -> Flask:
        """
        Supply the existing GUI application to each worker.

        :return: Flask WSGI application without an API proxy.
        """
        return self.application
