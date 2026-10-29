# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 2.0.0 - Unreleased

### Breaking changes
- Python 3.11 or newer is required. Python 3.9 and 3.10 are no longer supported.
- pytest-sftpserver is no longer used or installed. sftpmock now runs its own in-memory SFTP server, built on paramiko.
  `sftpmock.server.FixedContentProvider` has been removed.
- Server contents must be dicts (folders) holding `str` or `bytes` (files). Anything else raises a `TypeError` when
  the mock is created.
- Each server works on a copy of the contents passed in, so uploads no longer modify your dict and no longer carry
  over between calls of a decorated function. Use `with SFTPMock(...) as mock:` and read `mock.contents` to check
  uploaded files.
- Mocked hosts are redirected to `127.0.0.1` instead of `localhost`, so `transport.hostname` is now `"127.0.0.1"`.
- `rmdir` only removes empty folders and `remove` only removes files. Both used to delete folders with everything in
  them.
- Opening a file that does not exist (without creating it), or listing a folder that does not exist, raises
  `FileNotFoundError`.
- The `sftpmock` package only exports `SFTPMock` and `with_sftpmock`. It no longer re-exports `paramiko`, `socket`
  and the other names its star import exposed.
- Entering an `SFTPMock` that is already active raises `RuntimeError`.

### Added
- `SFTPMock.__enter__` returns the mock, and `SFTPMock.contents` shows the files and folders on each server, also
  after the mock has exited.
- Support for `lstat`, exclusive create (`open(path, "wx")`) and `posix_rename`.
- Type hints for the public API and a `py.typed` marker. Decorated functions keep their signature for type checkers.

### Fixed
- The package now declares its dependencies. 1.0.0 was published without any, so installing it did not install
  paramiko.
- Overwriting a file with shorter content replaces it, instead of failing with `size mismatch in put`.
- Non-ASCII `str` content is served as UTF-8 with its size in bytes, instead of being cut short.
- Empty files and folders can be renamed.
- Nested mocks work. Nesting used to fail with `KeyError: 'sock'`.
- Servers shut down immediately instead of after up to 0.5 seconds each, and close their open connections.
- Mocked connections no longer leave unclosed sockets behind where `localhost` resolves to IPv6 first.

### Changed
- paramiko 3.4.1 or newer is required, and paramiko 4 and 5 are supported.
- Server-side paramiko logs go to the `sftpmock.server.transport` logger instead of being printed to stderr.

## 1.0.0 - 2025-02-15

- First release.
