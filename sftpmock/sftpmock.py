from copy import deepcopy
from functools import wraps
from inspect import getcallargs
from typing import Dict, Optional

import paramiko
from socket import socket
from sftpmock.server import SFTPServer, validate_content
from unittest.mock import MagicMock


def _validate_host_contents(host_contents: dict):
    for content in host_contents.values():
        validate_content(content)


class SFTPMock(object):
    '''
    Act as a context to make local SFTP servers run for its duration

    Inspired by httmock's implementation
    '''

    # TODO have ways to test authentication errors by saving provided fake credentials

    def __init__(self, host_contents: dict):
        '''
        host_contents should be in the format:
        {
            "hostname": {
                "path": "content",
                "path2": "content2",
            }
        }
        '''

        _validate_host_contents(host_contents)

        self.host_contents = host_contents
        # set when servers start on __enter__
        self.host_servers: Dict[str, SFTPServer] = {}

    @property
    def contents(self) -> Dict[str, dict]:
        '''
        The files and folders on each mocked server, including any changes made while it ran
        '''
        return {host: server.content_provider.content_object for host, server in self.host_servers.items()}

    def __enter__(self):
        # We ignore original port, but there is a small likelyhoood of having two FTPs on the same hostname
        self.host_servers = {}
        try:
            for host, content in self.host_contents.items():
                # NOTE this opens a server on a Thread, in the future we might want to
                # mock server further to make it more like HTTMock and use only python objects and functions internally
                # Each server gets its own copy, so changes never reach host_contents or leak between runs
                server = SFTPServer(deepcopy(content))
                server.start()
                self.host_servers[host] = server
        except BaseException:
            self._stop_servers()
            raise

        host_ports = {host: server.port for host, server in self.host_servers.items()}

        # When nested, the current __init__ is another SFTPMock's fake one, which we call through to,
        # so hosts mocked by outer contexts keep working
        previous_init = paramiko.Transport.__init__
        real_init = getattr(previous_init, "_sftpmock_real_init", previous_init)

        def _fake_transport_init(*args, **kwargs):
            '''
            This is meant to replace Transport.__init__ to connect mocked hosts
            to the fake servers we created on 127.0.0.1
            '''
            # Transform all arguments into kwargs, to allow us to replace some of them
            kwargs = getcallargs(real_init, *args, **kwargs)
            sock = kwargs.pop("sock")

            # Extract real host and port from sock argument
            real_host = None
            real_port = None
            if isinstance(sock, socket):
                real_host = sock.getsockname()[0]
                real_port = sock.getsockname()[1]
            elif isinstance(sock, tuple):
                real_host, real_port = sock  # remove host and port that were passed
            elif isinstance(sock, str):
                real_host, real_port = sock.split(":")
            else:
                raise ValueError(
                    "sock argument must be a socket, a tuple or a string")

            # This keeps the connections our mock servers accept (which come from localhost)
            # and non-mocked connections unaffected
            if (real_host not in ("localhost", "127.0.0.1")) and (real_host in host_ports):
                # 127.0.0.1 rather than localhost, which may resolve to ::1 first where the servers don't listen
                previous_init(sock=("127.0.0.1", host_ports[real_host]), **kwargs)
            else:
                previous_init(sock=sock, **kwargs)

        _fake_transport_init._sftpmock_real_init = real_init

        # Make paramiko.Transport use our fake functions, remembering what to restore on exit
        self._previous_init = previous_init
        self._previous_server_ports = vars(paramiko.Transport).get("_fake_server_port")
        paramiko.Transport.__init__ = _fake_transport_init
        paramiko.Transport._fake_server_port = {**(self._previous_server_ports or {}), **host_ports}
        return self

    def __exit__(self, type, value, traceback):
        self._stop_servers()

        # Restore Transport to its state before __enter__
        paramiko.Transport.__init__ = self._previous_init
        if self._previous_server_ports is None:
            del paramiko.Transport._fake_server_port
        else:
            paramiko.Transport._fake_server_port = self._previous_server_ports

    def _stop_servers(self):
        for server in self.host_servers.values():
            # This makes sure server is properly closed without leaving any sockets hanging
            server.stop()


def with_sftpmock(host_contents: Optional[dict] = None):
    '''
    Decorator to makes the specified SFTP connections use a local, fake server

    host_contents should be in the format:
        {
            "mockedserver.com": {
                "folder": {
                    "sub_folder": {
                        "file.txt": "file content"
                    }
                }
            }
        }
    '''

    if host_contents is None:
        host_contents = {}
    # Fail when decorating, rather than each time the decorated function runs
    _validate_host_contents(host_contents)

    def decorator(func):
        @wraps(func)
        def inner(*inner_args, **kwargs):
            # Create local servers and replace Transport.__init__ to force connections to them,
            # using a new SFTPMock per call so calls never share state
            with SFTPMock(host_contents):
                return func(*inner_args, **kwargs)
        return inner
    return decorator
