# Developer guide

## Layout

```text
src/rewind/
  cli.py
  proxy/        stdio session, framing, discovery
  contracts/    YAML, JSON logic, redaction, business keys
  journal/      schema.sql, bootstrap, integrity, fencing
  platform/     Linux mountinfo and Darwin fstatfs
tests/
  unit/
  integration/
  subprocess/
examples/contracts/
docs/
```

`schema.sql` is loaded from the package directory. It contains no PRAGMA statements. Bootstrap executes one complete statement at a time with `Connection.execute` inside an explicit transaction. `executescript` is not used.

## Commands

```bash
python -m pip install -e ".[dev]"
python -m ruff check src tests
python -m ruff format --check src tests
python -m pytest
```

Subprocess tests launch `python -m rewind` and `tests/support/fake_upstream.py`. They are part of `pytest`, not a separate suite.

## Test hook

`Journal.open(..., ddl_failure_at=N)` aborts bootstrap before statement `N` and rolls the transaction back. It exists so tests can prove a failed DDL leaves no partial objects. The CLI does not expose it.

`Journal.fail_next_mutation` raises inside the next fenced write, after the epoch check and before any change, so the transaction rolls back. `after` skips that many writes first. `Journal.sibling_writer` opens a second connection on the same lease so two transactions can contend. Neither hook is on the CLI.

## CI

GitHub Actions runs lint and pytest on `ubuntu-latest`, `macos-14` (arm64), and `macos-13` (x86_64). Live `fstatfs` runs on the Darwin jobs and is skipped on Linux. A pass on one macOS architecture does not stand in for the other.

## Platform tests

Linux mount and `O_PATH` tests run only on Linux. The live Darwin `fstatfs` test runs only on Darwin and records `platform.machine()`. Unit tests for the `DarwinStatfs64` layout, NUL and UTF-8 failures, errno, and descriptor closure run on every host. Those unit tests do not mean a live Darwin call succeeded.

## Adding a contract field

Models use `extra=forbid` and strict types. A new field has to be added to the model, the loader's cross-checks, an example, and a test. Do not accept a string where a bool is required.
