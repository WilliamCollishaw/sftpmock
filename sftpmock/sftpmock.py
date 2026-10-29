from collections.abc import Callable, Mapping
from copy import deepcopy
from functools import wraps
from inspect import getcallargs
from socket import socket
from types import TracebackType
from typing import Any, ParamSpec, Self, TypeVar

import paramiko

from sftpmock.server import SFTPServer, validate_content

P = ParamSpec("P")
R = TypeVar("R")


def _validate_host_contents(host_contents: Mapping[str, Mapping[str, Any]]) -> None:
    for content in host_contents.values():
        validate_content(content)


class SFTPMock:
    """
    Context manager that runs local SFTP servers for its duration

    Inspired by httmock's implementation
    """

    # TODO have ways to test authentication errors by saving provided fake credentials

    def __init__(self, host_contents: Mapping[str, Mapping[str, Any]]) -> None:
        """
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
        """

        _validate_host_contents(host_contents)

        self.host_contents = host_contents
        # set when servers start on __enter__
        self.host_servers: dict[str, SFTPServer] = {}
        self._active = False

    @property
    def contents(self) -> dict[str, dict[str, Any]]:
        """
        The files and folders on each mocked server, including any changes made while it ran
        """
        return {host: server.content_provider.content_object for host, server in self.host_servers.items()}

    def __enter__(self) -> Self:
        if self._active:
            raise RuntimeError("This SFTPMock is already active, nest a new SFTPMock instead")

        self.host_servers = {}
        try:
            for host, content in self.host_contents.items():
                # NOTE this opens a server on a thread. In the future we might want to mock the server
                # further to make it more like httmock, using only Python objects and functions internally
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
            """
            This is meant to replace Transport.__init__ to connect mocked hosts
            to the fake servers we created on 127.0.0.1
            """
            # Transform all arguments into kwargs, to allow us to replace some of them
            kwargs = getcallargs(real_init, *args, **kwargs)
            sock = kwargs.pop("sock")

            # Extract the real host from the sock argument
            if isinstance(sock, socket):
                real_host = sock.getsockname()[0]
            elif isinstance(sock, tuple):
                real_host, _ = sock
            elif isinstance(sock, str):
                real_host, _ = sock.split(":")
            else:
                raise ValueError("sock argument must be a socket, a tuple or a string")

            # This keeps the connections our mock servers accept (which come from localhost)
            # and non-mocked connections unaffected
            # The port is ignored, so two SFTP servers on the same hostname can't be mocked separately
            if (real_host not in ("localhost", "127.0.0.1")) and (real_host in host_ports):
                # 127.0.0.1 rather than localhost, which may resolve to ::1 first where the servers don't listen
                previous_init(sock=("127.0.0.1", host_ports[real_host]), **kwargs)
            else:
                previous_init(sock=sock, **kwargs)

        _fake_transport_init._sftpmock_real_init = real_init

        # Make paramiko.Transport use our fake __init__ and ports, remembering what to restore on exit
        self._previous_init = previous_init
        self._previous_server_ports = vars(paramiko.Transport).get("_fake_server_port")
        paramiko.Transport.__init__ = _fake_transport_init
        paramiko.Transport._fake_server_port = {**(self._previous_server_ports or {}), **host_ports}
        self._active = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._stop_servers()
        self._active = False

        # Restore Transport to its state before __enter__
        paramiko.Transport.__init__ = self._previous_init
        if self._previous_server_ports is None:
            del paramiko.Transport._fake_server_port
        else:
            paramiko.Transport._fake_server_port = self._previous_server_ports

    def _stop_servers(self) -> None:
        for server in self.host_servers.values():
            # This makes sure the server is properly closed without leaving any sockets hanging
            server.stop()


def with_sftpmock(
    host_contents: Mapping[str, Mapping[str, Any]] | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Decorator to make the specified SFTP connections use a local, fake server

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
    """

    if host_contents is None:
        host_contents = {}
    # Fail when decorating, rather than each time the decorated function runs
    _validate_host_contents(host_contents)

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def inner(*args: P.args, **kwargs: P.kwargs) -> R:
            # Create local servers and replace Transport.__init__ to force connections to them,
            # using a new SFTPMock per call so calls never share state
            with SFTPMock(host_contents):
                return func(*args, **kwargs)

        return inner

    return decorator
