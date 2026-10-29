![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Tests](https://github.com/Doctor-God/sftpmock/actions/workflows/test.yml/badge.svg?branch=main)
[![Python versions](https://img.shields.io/pypi/pyversions/sftpmock)](https://pypi.org/project/sftpmock/)

# sftpmock
Allows you to test behavior that relies on external SFTP servers to function. This means you can "replace" the
external server with a local, mocked version of it, testing behavior that relies on certain files being or not being present
on said server.

We do this by locally modifying `paramiko.Transport.__init__` to redirect real server addresses to internal mocked servers.

This was inspired by [**httmock**](https://github.com/patrys/httmock)'s implementation. Check them out!

The mocked SFTP servers are based on the design of [**pytest-sftpserver**](https://github.com/ulope/pytest-sftpserver).

## Installation
```sh
pip install sftpmock
```

sftpmock requires Python 3.11 or newer and paramiko 3.4.1 or newer, which is installed with it.

## How to use

### Applying the mock
You can use sftpmock either as a decorator or as a context manager, like so:
```python
from sftpmock import SFTPMock, with_sftpmock

# DECORATOR
@with_sftpmock({})
def test_function():
    # Do your asserts here

# CONTEXT MANAGER
def test_function():
    with SFTPMock({}):
        # Do your asserts here
```

### Servers
With either method, sftpmock expects a `host_contents` input dict. This dictionary follows this syntax:
```python
{
    "mockedserver.com": {
        "folder": {
            "sub_folder": {
                "file.txt": "file content"
            }
        }
    }
}
```
The folder structure has no depth limit and can contain any number of files.

Folders are dicts, and files are `str` (served as UTF-8) or `bytes`. Anything else raises a `TypeError` when the mock is
created. An empty dict is an empty folder.

You may also mock more than one server if needed.

## Examples
### General use
Normally you'd use sftpmock like this:
```python
@with_sftpmock({
    "test.com": {"a_folder": {"coisa.txt": "some text"}}
})
def test_function():
    # Do your asserts here
```

### Calling `paramiko.Transport` in a test function
`paramiko.Transport` can be imported as usual: the mock applies to it wherever it was imported. The mocked servers
accept any credentials.
```python
from paramiko import SFTPClient, Transport

@with_sftpmock({
    "test.com": {"a_folder": {"coisa.txt": "some text"}}
})
def test_function():
    with Transport(("test.com", 22)) as transport:
        transport.connect(username="user", password="pass")
        sftp = SFTPClient.from_transport(transport)

        assert sftp.listdir("/a_folder") == ["coisa.txt"]
```

### Mocking multiple servers
If you need to mock more than one server, simply add it to the input dict.

```python
@with_sftpmock({
    "test.com": {"a_folder": {"coisa.txt": "some text"}},
    "otherdomain.com": {"a_folder": {"another.txt": "another text"}}
})
def test_function():
    # Do your asserts here
```

### Checking uploaded files
Each server works on a copy of the contents you pass in, so your dict is never changed and every run starts from the
same files. To check what your code uploaded, use the context manager and read `contents` from the returned mock.

```python
def test_function():
    with SFTPMock({"test.com": {"a_folder": {}}}) as mock:
        upload_report()  # your code that uploads /a_folder/report.csv

        assert "report.csv" in mock.contents["test.com"]["a_folder"]
```

Uploaded files are stored as `bytes`.

### Using a socket
If you pass a socket to `Transport`, you may run into errors because the socket still tries to connect to the real server, even though sftpmock ignores that connection.

One way around this is to use `unittest.mock` to prevent that initial socket connection. From there, sftpmock works as expected.

```python
import socket
from unittest import mock

from paramiko import Transport

@with_sftpmock({
    "test.com": {"a_folder": {"test.txt": "some text"}},
})
@mock.patch("socket.socket", spec=socket.socket)
def test_function(mock_socket):
    mock_socket.return_value.getsockname.return_value = ("test.com", 22)

    serversocket = socket.socket()

    serversocket.connect(("test.com", 22))

    with Transport(serversocket) as transport:
        # Do your asserts here
```

## Known Issues / Limitations
- Checking the host and port in `transport.sock` may fail, as they are replaced by `127.0.0.1` and a random local port
- `paramiko.SSHClient` is not mocked, as it connects to the real host itself before creating a `Transport`. Use `paramiko.Transport` directly instead
- If you are passing a socket to `Transport`, you may need to mock it first
- Servers on `localhost` or `127.0.0.1` can't be mocked
- The port is ignored: all connections to a mocked hostname reach the same server
- Any credentials are accepted, so authentication failures can't be tested

## Future improvements
- Allow for server port differentiation
- Support `paramiko.SSHClient`
- Allow testing authentication failures
