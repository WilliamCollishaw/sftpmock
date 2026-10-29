from contextlib import contextmanager
from io import BytesIO, StringIO
import socket
from unittest import TestCase

import paramiko

from sftpmock import SFTPMock, with_sftpmock
from unittest import mock


@contextmanager
def sftp_client(host="test.com"):
    with paramiko.Transport((host, 22)) as transport:
        transport.connect(None, "user", "pass")
        yield paramiko.SFTPClient.from_transport(transport)


class SFTPMockerTest(TestCase):
    '''
    This tests core functionality of the "with_sftpmock" decorator
    '''

    @with_sftpmock({
        "test.com": {"Outbound": {"file.txt": "some text"}},
        "otherdomain.com": {"Outbound": {"another.TXT": "another text"}}
    })
    def test_fake_server_port_set_correctly(self):
        '''
        Tests if Connection was mocked to include the hostname -> port attribute (_fake_server_port)
        '''
        # Import needs to happen here because we want to use mocked Transport
        from paramiko import Transport

        assert hasattr(
            Transport, "_fake_server_port"), "Transport class should have mocked _fake_server_port attribute"

        assert isinstance(Transport._fake_server_port, dict)

        assert "test.com" in Transport._fake_server_port, "Transport should have 'test.com' as _fake_server_port key"
        assert "otherdomain.com" in Transport._fake_server_port, "Transport should have 'otherdomain.com' as _fake_server_port key"

        assert Transport._fake_server_port["test.com"] is not None, "Transport should have a port for 'test.com'"
        assert Transport._fake_server_port["otherdomain.com"] is not None, "Transport should have a port for 'otherdomain.com'"

        assert Transport._fake_server_port["test.com"] != Transport._fake_server_port[
            "otherdomain.com"], "Transport should have different ports for different hosts"

    @with_sftpmock({
        "test.com": {"a_folder": {"file.txt": "some text"}},
    })
    def test_getfo_operation(self):
        '''
        Test if SFTPClient.getfo works as expected 
        '''
        # Import needs to happen here because we need to use mocked Transport
        from paramiko import Transport

        with Transport(("test.com", 22)) as transport:
            transport.connect(None, "user", "pass")
            client = paramiko.SFTPClient.from_transport(transport)

            outfile = BytesIO()
            client.getfo("/a_folder/file.txt", outfile)
            assert outfile.getvalue().decode('utf-8') == "some text"

    @with_sftpmock({
        "test.com": {"a_folder": {"file.txt": "some text"}},
    })
    def test_putfo_operation(self):
        '''
        Test if Connection.putfo works as expected 
        '''
        # Import needs to happen here because we need to use mocked Transport
        from paramiko import Transport

        with Transport(("test.com", 22)) as transport:
            transport.connect(None, "user", "pass")
            client = paramiko.SFTPClient.from_transport(transport)

            client.putfo(StringIO("texto aleatorio"),
                         "/a_folder/outro_arquivo")

            outfile = BytesIO()
            client.getfo("/a_folder/outro_arquivo", outfile)
            assert outfile.getvalue().decode('utf-8') == "texto aleatorio"

    @with_sftpmock({
        "test.com": {"a_folder": {"file.txt": "some text"}, "other_folder": {}},
    })
    def test_listdir_operation(self):
        '''
        Test if Connection.putfo works as expected 
        '''
        # Import needs to happen here because we need to use mocked Transport
        from paramiko import Transport

        with Transport(("test.com", 22)) as transport:
            transport.connect(None, "user", "pass")
            client = paramiko.SFTPClient.from_transport(transport)

            records = client.listdir()
            assert records == ["a_folder", "other_folder"], \
                f"Expected '[a_folder, other_folder]', found {records}"

            records = client.listdir("/")
            assert records == ["a_folder", "other_folder"], \
                f"Expected '[a_folder, other_folder]', found {records}"

            records = client.listdir("/a_folder")
            assert records == ["file.txt"], \
                f"Expected '[file.txt]', found {records}"

            records = client.listdir("/other_folder")
            assert records == [], \
                f"Expected '[]', found {records}"

    @with_sftpmock({
        "test.com": {"a_folder": {"coisa.txt": "some text"}},
        "otherdomain.com": {"a_folder": {"another.txt": "another text"}}
    })
    def test_both_connections_work_independently(self):
        '''
        Test if nested connections work correctly as two separate servers 
        '''
        # Import needs to happen here because we need to use mocked Transport
        from paramiko import Transport

        with Transport(("test.com", 22)) as transport:
            transport.connect(None, "user", "pass")
            client = paramiko.SFTPClient.from_transport(transport)

            records = client.listdir("/a_folder")
            assert records == ["coisa.txt"], \
                f"Expected '[coisa.txt]', found {records}"

            with Transport(("otherdomain.com", 22)) as transport:
                transport.connect(None, "user", "pass")
                other_client = paramiko.SFTPClient.from_transport(transport)

                records = other_client.listdir("/a_folder")
                assert records == ["another.txt"], \
                    f"Expected '[another.txt]', found {records}"

    def test_servers_are_shutdown_normally(self):
        '''
        Test if servers are shutdown when execution ends normally.

        We test SFTPMock directly because we need to check its variables
        '''
        servers_context = SFTPMock({
            "test.com": {"Outbound": {"file.TXT": "some text"}},
            "otherdomain.com": {"Outbound": {"another.TXT": "another text"}}
        })

        assert not servers_context.host_servers, "Servers should not be started yet"

        with servers_context:
            assert all(server.port for server in servers_context.host_servers.values(
            )), "Servers should be started"

        assert all(not server.is_alive() for server in servers_context.host_servers.values()), \
            "Servers should be stopped"

        assert all(server.socket._closed for server in servers_context.host_servers.values()), \
            "All sockets should be closed"

    def test_servers_are_shutdown_exception(self):
        '''
        Test if servers are shutdown when an exception is raised

        We test SFTPMock directly because we need to check its variables
        '''
        servers_context = SFTPMock({
            "test.com": {"Outbound": {"file.TXT": "some text"}},
            "otherdomain.com": {"Outbound": {"another.TXT": "another text"}}
        })

        assert not servers_context.host_servers, "Servers should not be started yet"

        try:
            with servers_context:
                assert all(server.port for server in servers_context.host_servers.values(
                )), "Servers should be started"
                raise Exception("Some error")
        except Exception as e:
            pass

        assert all(not server.is_alive() for server in servers_context.host_servers.values()), \
            "Servers should be stopped"

        assert all(server.socket._closed for server in servers_context.host_servers.values()), \
            "All sockets should be closed"

    @with_sftpmock({
        "test.com": {},
    })
    def test_init_with_string(self):
        '''
        Test if Transport can be initialized with a string as sock argument
        '''
        # Import needs to happen here because we need to use mocked Transport
        from paramiko import Transport

        with Transport("test.com:22") as transport:
            assert transport.hostname == "127.0.0.1"

    @with_sftpmock({
        "test.com": {},
    })
    def test_init_with_tuple(self):
        '''
        Test if Transport can be initialized with a tuple as sock argument
        '''
        # Import needs to happen here because we need to use mocked Transport
        from paramiko import Transport

        with Transport(("test.com", 22)) as transport:
            assert transport.hostname == "127.0.0.1"

    @with_sftpmock({
        "test.com": {},
    })
    @mock.patch('socket.socket', spec=socket.socket)
    def test_init_with_socket(self, mock_socket):
        '''
        Test if Transport can be initialized with a socket as sock argument
        '''
        # Import needs to happen here because we need to use mocked Transport
        from paramiko import Transport

        mock_socket.return_value.getsockname.return_value = ("test.com", 22)

        serversocket = socket.socket()

        serversocket.connect(("test.com", 22))

        with Transport(serversocket) as transport:
            assert transport.hostname == "127.0.0.1"

    @with_sftpmock({
        "test.com": {},
    })
    def test_other_connections(self):
        '''
        Test if a non-mocked server is unnafected by the decorator
        '''
        # NOTE this test does an actual connection and tests if it fails, which it should
        # This also means this test is slighly slower, due to timeout not being changeable in this case

        # Import needs to happen here because we need to use mocked Transport
        from paramiko import Transport

        with mock.patch('socket.getaddrinfo') as mock_getaddrinfo:
            try:
                with Transport("example.com:22") as transport:
                    pass
            except:
                # This raises and exception because of the mocked getaddrinfo,
                # but we only want to know if the connection was attempted, meaning it was not mocked
                pass
            mock_getaddrinfo.assert_called_once_with(
                "example.com", 22, socket.AF_UNSPEC, socket.SOCK_STREAM)


class SFTPServerBehaviourTest(TestCase):
    '''
    This tests how the mocked SFTP servers handle files and folders
    '''

    @with_sftpmock({
        "test.com": {"a_folder": {"file.txt": "some longer text"}},
    })
    def test_overwrite_truncates_file(self):
        '''
        Test if writing a shorter file over an existing one replaces its content
        '''
        with sftp_client() as client:
            client.putfo(BytesIO(b"short"), "/a_folder/file.txt")

            outfile = BytesIO()
            client.getfo("/a_folder/file.txt", outfile)
            assert outfile.getvalue() == b"short", f"Expected b'short', found {outfile.getvalue()}"

    @with_sftpmock({
        "test.com": {"a_folder": {"file.txt": "some text"}},
    })
    def test_exclusive_create(self):
        '''
        Test if opening with exclusive create fails for existing files and works for new ones
        '''
        with sftp_client() as client:
            with self.assertRaises(OSError):
                client.open("/a_folder/file.txt", "wx")

            with client.open("/a_folder/new.txt", "wx") as f:
                f.write(b"new text")
            assert sorted(client.listdir("/a_folder")) == ["file.txt", "new.txt"]

    @with_sftpmock({
        "test.com": {"a_folder": {"file.txt": "café ✓"}},
    })
    def test_non_ascii_text_content(self):
        '''
        Test if str content is served as UTF-8, with sizes counted in bytes
        '''
        with sftp_client() as client:
            assert client.stat("/a_folder/file.txt").st_size == len("café ✓".encode())

            outfile = BytesIO()
            client.getfo("/a_folder/file.txt", outfile)
            assert outfile.getvalue().decode("utf-8") == "café ✓"

    @with_sftpmock({
        "test.com": {"a_folder": {"file.bin": b"\x00\x01\xff"}},
    })
    def test_bytes_content(self):
        '''
        Test if bytes content is served as is
        '''
        with sftp_client() as client:
            outfile = BytesIO()
            client.getfo("/a_folder/file.bin", outfile)
            assert outfile.getvalue() == b"\x00\x01\xff"

    @with_sftpmock({
        "test.com": {"a_folder": {"file.txt": "some text"}},
    })
    def test_missing_paths_raise(self):
        '''
        Test if opening, listing or stat-ing a path that does not exist raises FileNotFoundError
        '''
        with sftp_client() as client:
            with self.assertRaises(FileNotFoundError):
                client.open("/a_folder/missing.txt")
            with self.assertRaises(FileNotFoundError):
                client.listdir("/missing_folder")
            with self.assertRaises(FileNotFoundError):
                client.stat("/a_folder/missing.txt")

    @with_sftpmock({
        "test.com": {"a_folder": {"file.txt": "some text"}},
    })
    def test_lstat(self):
        '''
        Test if lstat works like stat, as there are no symlinks
        '''
        with sftp_client() as client:
            assert client.lstat("/a_folder/file.txt").st_size == len("some text")

    @with_sftpmock({
        "test.com": {"a_folder": {"file.txt": "some text"}},
    })
    def test_mkdir_and_rmdir(self):
        '''
        Test if folders can be created and removed, and that only empty folders can be removed
        '''
        with sftp_client() as client:
            client.mkdir("/new_folder")
            assert sorted(client.listdir("/")) == ["a_folder", "new_folder"]

            client.rmdir("/new_folder")
            assert client.listdir("/") == ["a_folder"]

            with self.assertRaises(OSError):
                client.rmdir("/a_folder")
            assert client.listdir("/a_folder") == ["file.txt"]

    @with_sftpmock({
        "test.com": {"a_folder": {"file.txt": "some text"}},
    })
    def test_remove(self):
        '''
        Test if files can be removed, but folders can not
        '''
        with sftp_client() as client:
            with self.assertRaises(OSError):
                client.remove("/a_folder")
            assert client.listdir("/") == ["a_folder"]

            client.remove("/a_folder/file.txt")
            assert client.listdir("/a_folder") == []

    @with_sftpmock({
        "test.com": {"a_folder": {"file.txt": "some text", "other.txt": "other text", "empty.txt": ""}},
    })
    def test_rename(self):
        '''
        Test if rename moves files, refuses to overwrite, and posix_rename overwrites
        '''
        with sftp_client() as client:
            client.rename("/a_folder/file.txt", "/a_folder/renamed.txt")
            assert sorted(client.listdir("/a_folder")) == ["empty.txt", "other.txt", "renamed.txt"]

            client.rename("/a_folder/empty.txt", "/a_folder/still_empty.txt")
            assert sorted(client.listdir("/a_folder")) == ["other.txt", "renamed.txt", "still_empty.txt"]

            with self.assertRaises(OSError):
                client.rename("/a_folder/renamed.txt", "/a_folder/other.txt")

            client.posix_rename("/a_folder/renamed.txt", "/a_folder/other.txt")
            outfile = BytesIO()
            client.getfo("/a_folder/other.txt", outfile)
            assert outfile.getvalue() == b"some text"

    def test_unsupported_content_raises(self):
        '''
        Test if content that is not a dict, str or bytes is rejected up front
        '''
        with self.assertRaises(TypeError):
            SFTPMock({"test.com": {"a_folder": {"file.txt": 123}}})


class SFTPMockStateTest(TestCase):
    '''
    This tests that mocks don't share or leak state
    '''

    def test_decorated_calls_do_not_share_state(self):
        '''
        Test if each call of a decorated function starts from the original content
        '''
        @with_sftpmock({"test.com": {"a_folder": {}}})
        def upload():
            with sftp_client() as client:
                before = client.listdir("/a_folder")
                client.putfo(BytesIO(b"some text"), "/a_folder/new.txt")
                return before

        assert upload() == []
        assert upload() == [], "Second call should not see the file uploaded by the first call"

    def test_contents_are_not_modified(self):
        '''
        Test if uploads don't change the dict passed in, by the decorator or the context manager
        '''
        contents = {"test.com": {"a_folder": {"file.txt": "some text"}}}

        @with_sftpmock(contents)
        def upload():
            with sftp_client() as client:
                client.putfo(BytesIO(b"other text"), "/a_folder/file.txt")
                client.putfo(BytesIO(b"new text"), "/a_folder/new.txt")

        upload()
        with SFTPMock(contents):
            upload.__wrapped__()

        assert contents == {"test.com": {"a_folder": {"file.txt": "some text"}}}

    def test_contents_exposed_on_mock(self):
        '''
        Test if the context manager returns the mock, which exposes the server contents
        '''
        with SFTPMock({"test.com": {"a_folder": {}}}) as mock:
            with sftp_client() as client:
                client.putfo(BytesIO(b"some text"), "/a_folder/new.txt")

            assert mock.contents["test.com"]["a_folder"]["new.txt"] == b"some text"

        # Still readable after the servers stop
        assert mock.contents["test.com"]["a_folder"]["new.txt"] == b"some text"

    def test_nested_mocks(self):
        '''
        Test if nested mocks work together, and each exit restores the state before its enter
        '''
        original_init = paramiko.Transport.__init__

        with SFTPMock({"test.com": {"outer.txt": "outer"}}):
            with SFTPMock({"otherdomain.com": {"inner.txt": "inner"}}):
                with sftp_client("test.com") as client:
                    assert client.listdir("/") == ["outer.txt"]
                with sftp_client("otherdomain.com") as client:
                    assert client.listdir("/") == ["inner.txt"]
                assert set(paramiko.Transport._fake_server_port) == {"test.com", "otherdomain.com"}

            with sftp_client("test.com") as client:
                assert client.listdir("/") == ["outer.txt"]
            assert set(paramiko.Transport._fake_server_port) == {"test.com"}

        assert paramiko.Transport.__init__ is original_init
        assert not hasattr(paramiko.Transport, "_fake_server_port")

    def test_decorator_without_contents(self):
        '''
        Test if the decorator works without any contents
        '''
        @with_sftpmock()
        def decorated():
            return paramiko.Transport._fake_server_port

        assert decorated() == {}

    def test_unsupported_content_raises_when_decorating(self):
        '''
        Test if unsupported content is rejected when decorating, not when the test runs
        '''
        with self.assertRaises(TypeError):
            with_sftpmock({"test.com": {"file.txt": 123}})
