from functools import wraps
from inspect import getcallargs
from typing import Dict

import paramiko
from socket import socket
from sftpmock.server import SFTPServer, validate_content
from unittest.mock import MagicMock


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

        for content in host_contents.values():
            validate_content(content)

        self.host_contents = host_contents
        # set when servers start on __enter__
        self.host_servers: Dict[str, SFTPServer] = {}

    def __enter__(self):
        # We ignore original port, but there is a small likelyhoood of having two FTPs on the same hostname
        for host, content in self.host_contents.items():
            # NOTE this opens a server on a Thread, in the future we might want to
            # mock server further to make it more like HTTMock and use only python objects and functions internally
            server = SFTPServer(content)
            server.start()
            self.host_servers[host] = server

        self._real_Transport__init__ = paramiko.Transport.__init__

        def _fake_transport_init(*args, **kwargs):
            '''
            This is meat to replace Transport.__init__ to always connect to localhost
            on the fake servers we created
            '''
            # Transform all arguments into kwargs, to allow us to replace some of them
            kwargs = getcallargs(
                self._real_Transport__init__, *args, **kwargs)
            transport_self = kwargs.get("self")
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
            if (real_host not in ("localhost", "127.0.0.1")) and (real_host in transport_self._fake_server_port):
                self._real_Transport__init__(
                    sock=("localhost", transport_self._fake_server_port[real_host]), **kwargs)
            else:
                self._real_Transport__init__(sock=sock, **kwargs)

        # Make paramiko.Transport use our fake functions
        paramiko.Transport.__init__ = _fake_transport_init
        paramiko.Transport._fake_server_port = {
            host: server.port for host, server in self.host_servers.items()}

    def __exit__(self, type, value, traceback):
        # Stop servers
        for server in self.host_servers.values():
            # This makes sure server is properly closed without leaving any sockets hanging
            server.stop()

        # Restore Transport to its original state
        paramiko.Transport.__init__ = self._real_Transport__init__
        del paramiko.Transport._fake_server_port


def with_sftpmock(host_contents: dict = {}):
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

    # Create a local, fake server
    servers_context = SFTPMock(host_contents)

    def decorator(func):
        @wraps(func)
        def inner(*inner_args, **kwargs):
            # Create a local server and replace Connection.__init__ to force connection to that server
            with servers_context:
                return func(*inner_args, **kwargs)
        return inner
    return decorator
