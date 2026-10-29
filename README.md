![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Tests](https://github.com/Doctor-God/sftpmock/actions/workflows/test.yml/badge.svg?branch=main) 
[![Python versions](https://img.shields.io/pypi/pyversions/sftpmock)](https://pypi.org/project/sftpmock/)

# sftpmock
Allows you to test behavior that relies on external SFTP servers to function. This means you can "replace" the
external server with a local, mocked version of it, testing behavior that relies on certain files being or not being present
on said server.

We do this by locally modifying ```paramiko.Transport.__init__``` to redirect real server addresses to internal mocked servers.

This was inspired by [**httmock**](https://github.com/patrys/httmock)'s implementation, check them out!

The mocked SFTP servers are based on the design of [**pytest-sftpserver**](https://github.com/ulope/pytest-sftpserver).

## How to use

### Applying the mock
You can use sftpmock both as a decorator, or as a context manager, like so:
```python
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
On both of the methods, sftpmock expects a ```server_contents``` input dict. This dictionary follows this syntax:
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

### Calling paramiko.Transport on test function
If you need to call ```paramiko.Transport``` directly on the test function, you need to import it on the function. This makes sure the mocked version of ```Transport``` is used.

On other use cases this is not necessary.
```python
@with_sftpmock({
    "test.com": {"a_folder": {"coisa.txt": "some text"}}
})
def test_function():
    from paramiko import Transport

    with Transport(("test.com", 22)) as transport:
        # Do your asserts here
```

### Mocking multiple servers
If you need to mock more than one server, simply include it on the input dict.

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
If you use Python sockets, you may run into errors when the socket still tries to connect to the real server, even though sftpmock ignores that connection.

One way to circumvent that is by using ```unnitest.mock``` to prevent that initial socket connection. From there, sftpmock works as expected. 

```python
import socket

@with_sftpmock({
    "test.com": {"a_folder": {"test.txt": "some text"}},
})
@mock.patch('socket.socket', spec=socket.socket)
def test_function(self, mock_socket):
    from paramiko import Transport

    mock_socket.return_value.getsockname.return_value = ("test.com", 22)

    serversocket = socket.socket()

    serversocket.connect(("test.com", 22))

    with Transport(serversocket) as transport:
        # Do your asserts here
```

## Known Issues / Limitations
- Trying to test transport.sock hostname and ports may result in errors, as they are replaced by 127.0.0.1 and a random local port
- SSHClient may be replaced by a local server, as it also uses paramiko.Transport (need to test this still)
- If you are using sockets to init a Transport, you may need to mock them first
- If the SFTP servers being tested are actually localhost, this won't work

## Future improvements
- Allow for server port differentiation
- Avoid affecting SSHClient