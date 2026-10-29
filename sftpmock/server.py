'''
A minimal in-memory SFTP server, serving a nested dict where folders are dicts
and files are str or bytes.

Based on the design of pytest-sftpserver (https://github.com/ulope/pytest-sftpserver, MIT License).
'''

import functools
import logging
import os
import posixpath
import socketserver
import stat
import threading
import time

import paramiko
from paramiko.sftp import SFTP_FAILURE, SFTP_NO_SUCH_FILE, SFTP_OK

# Server-side paramiko logs go here, and are only shown if the application configures logging
logging.getLogger(__name__).addHandler(logging.NullHandler())


def validate_content(content, path="/"):
    '''
    Raise TypeError if content contains anything other than dicts (folders) and str or bytes (files)
    '''
    if isinstance(content, dict):
        for name, child in content.items():
            validate_content(child, posixpath.join(path, str(name)))
    elif not isinstance(content, (str, bytes)):
        raise TypeError(
            f"Unsupported content at {path!r}: expected a dict (folder) or str/bytes (file), "
            f"got {type(content).__name__}")


def _normalize(path):
    return posixpath.normpath(posixpath.join("/", path))


def _as_bytes(content):
    return content.encode("utf-8") if isinstance(content, str) else content


class ContentProvider(object):
    '''
    Reads and writes the files and folders of a nested dict, by absolute path
    '''

    def __init__(self, content_object=None):
        self.content_object = {} if content_object is None else content_object

    def get(self, path):
        obj = self.content_object
        for part in path.split("/"):
            if not part:
                continue
            if not isinstance(obj, dict) or part not in obj:
                return None
            obj = obj[part]
        return obj

    def put(self, path, data):
        parent_path, name = posixpath.split(path)
        parent = self.get(parent_path)
        if not name or not isinstance(parent, dict):
            return False
        parent[name] = data
        return True

    def remove(self, path):
        parent_path, name = posixpath.split(path)
        parent = self.get(parent_path)
        if not isinstance(parent, dict) or name not in parent:
            return False
        del parent[name]
        return True


def _attributes(content_provider, path):
    content = content_provider.get(path)
    if content is None:
        return SFTP_NO_SUCH_FILE

    attributes = paramiko.SFTPAttributes()
    attributes.filename = posixpath.basename(path)
    if isinstance(content, dict):
        attributes.st_mode = stat.S_IFDIR | 0o777
        attributes.st_size = 0
    else:
        attributes.st_mode = stat.S_IFREG | 0o777
        attributes.st_size = len(_as_bytes(content))
    attributes.st_uid = 0
    attributes.st_gid = 0
    attributes.st_atime = attributes.st_mtime = int(time.time())
    return attributes


class _SFTPHandle(paramiko.SFTPHandle):
    def __init__(self, content_provider, path, flags=0):
        super().__init__(flags)
        self.content_provider = content_provider
        self.path = path

    def read(self, offset, length):
        content = self.content_provider.get(self.path)
        if content is None:
            return SFTP_NO_SUCH_FILE
        if isinstance(content, dict):
            return SFTP_FAILURE
        return _as_bytes(content)[offset:offset + length]

    def write(self, offset, data):
        content = self.content_provider.get(self.path)
        if isinstance(content, dict):
            return SFTP_FAILURE
        content = b"" if content is None else _as_bytes(content)
        if offset > len(content):
            content += b"\x00" * (offset - len(content))
        content = content[:offset] + data + content[offset + len(data):]
        return SFTP_OK if self.content_provider.put(self.path, content) else SFTP_NO_SUCH_FILE

    def stat(self):
        return _attributes(self.content_provider, self.path)

    def chattr(self, attr):
        return SFTP_OK if self.content_provider.get(self.path) is not None else SFTP_NO_SUCH_FILE


class _SFTPServerInterface(paramiko.SFTPServerInterface):
    def __init__(self, server, *args, content_provider, **kwargs):
        super().__init__(server, *args, **kwargs)
        self.content_provider = content_provider

    def list_folder(self, path):
        path = _normalize(path)
        content = self.content_provider.get(path)
        if content is None:
            return SFTP_NO_SUCH_FILE
        if not isinstance(content, dict):
            return SFTP_FAILURE
        return [_attributes(self.content_provider, posixpath.join(path, name)) for name in content]

    def stat(self, path):
        return _attributes(self.content_provider, _normalize(path))

    # There are no symlinks, so lstat is the same as stat
    lstat = stat

    def open(self, path, flags, attr):
        path = _normalize(path)
        content = self.content_provider.get(path)
        if isinstance(content, dict):
            return SFTP_FAILURE
        if content is None:
            if not flags & os.O_CREAT:
                return SFTP_NO_SUCH_FILE
            if not self.content_provider.put(path, b""):
                return SFTP_NO_SUCH_FILE
        elif flags & os.O_CREAT and flags & os.O_EXCL:
            return SFTP_FAILURE
        elif flags & os.O_TRUNC:
            self.content_provider.put(path, b"")
        return _SFTPHandle(self.content_provider, path, flags)

    def remove(self, path):
        path = _normalize(path)
        content = self.content_provider.get(path)
        if content is None:
            return SFTP_NO_SUCH_FILE
        if isinstance(content, dict):
            return SFTP_FAILURE
        self.content_provider.remove(path)
        return SFTP_OK

    def rename(self, oldpath, newpath):
        newpath = _normalize(newpath)
        if self.content_provider.get(newpath) is not None:
            return SFTP_FAILURE
        return self._move(_normalize(oldpath), newpath)

    def posix_rename(self, oldpath, newpath):
        return self._move(_normalize(oldpath), _normalize(newpath))

    def _move(self, oldpath, newpath):
        content = self.content_provider.get(oldpath)
        if content is None:
            return SFTP_NO_SUCH_FILE
        if oldpath == newpath:
            return SFTP_OK
        # Moving the root, or a folder into itself, would create a cycle
        if oldpath == "/" or newpath.startswith(oldpath + "/"):
            return SFTP_FAILURE
        if not self.content_provider.put(newpath, content):
            return SFTP_NO_SUCH_FILE
        self.content_provider.remove(oldpath)
        return SFTP_OK

    def mkdir(self, path, attr):
        path = _normalize(path)
        if self.content_provider.get(path) is not None:
            return SFTP_FAILURE
        return SFTP_OK if self.content_provider.put(path, {}) else SFTP_NO_SUCH_FILE

    def rmdir(self, path):
        path = _normalize(path)
        content = self.content_provider.get(path)
        if content is None:
            return SFTP_NO_SUCH_FILE
        if path == "/" or not isinstance(content, dict) or content:
            return SFTP_FAILURE
        self.content_provider.remove(path)
        return SFTP_OK

    def chattr(self, path, attr):
        return SFTP_OK if self.content_provider.get(_normalize(path)) is not None else SFTP_NO_SUCH_FILE


class _AllowAllServer(paramiko.ServerInterface):
    '''
    Accepts any credentials
    '''

    def get_allowed_auths(self, username):
        return "none,password,publickey"

    def check_auth_none(self, username):
        return paramiko.AUTH_SUCCESSFUL

    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL

    def check_auth_publickey(self, username, key):
        return paramiko.AUTH_SUCCESSFUL

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED


@functools.cache
def _host_key():
    # Generated once per process, as this takes a moment
    return paramiko.RSAKey.generate(2048)


class _SFTPRequestHandler(socketserver.BaseRequestHandler):
    def handle(self):
        transport = paramiko.Transport(self.request)
        transport.set_log_channel(f"{__name__}.transport")
        self.server._transports.add(transport)
        try:
            transport.add_server_key(_host_key())
            transport.set_subsystem_handler(
                "sftp", paramiko.SFTPServer, _SFTPServerInterface,
                content_provider=self.server.content_provider)
            try:
                transport.start_server(server=_AllowAllServer())
            except (paramiko.SSHException, EOFError, OSError):
                # The client went away before finishing the SSH handshake
                return
            # Keep serving until the client disconnects or the server is stopped
            transport.join()
        finally:
            transport.close()
            self.server._transports.discard(transport)


class SFTPServer(socketserver.ThreadingTCPServer):
    '''
    Serves content_object over SFTP on a random localhost port, from a background thread
    '''

    daemon_threads = True

    def __init__(self, content_object=None):
        super().__init__(("127.0.0.1", 0), _SFTPRequestHandler)
        self.content_provider = ContentProvider(content_object)
        self._transports = set()
        self._thread = threading.Thread(
            target=self.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)

    @property
    def port(self):
        return self.server_address[1]

    def start(self):
        self._thread.start()

    def is_alive(self):
        return self._thread.is_alive()

    def stop(self):
        '''
        Stop serving, close all connections and wait for the server thread to finish
        '''
        if self._thread.is_alive():
            self.shutdown()
        self.server_close()
        for transport in list(self._transports):
            transport.close()
        if self._thread.ident is not None:
            self._thread.join()
