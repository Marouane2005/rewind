"""Public error types.

These errors fail closed. Callers must not treat them as permission to retry
a side effect or to recreate an existing database.
"""


class RewindError(Exception):
    """Base error for expected REWIND failures."""


class UnsupportedPlatformError(RewindError):
    """The host platform or required OS primitive is not supported."""


class FilesystemValidationError(RewindError):
    """Mount or filesystem metadata could not be validated."""


class UnsupportedFilesystemError(FilesystemValidationError):
    """The resolved filesystem is outside the allowlist."""


class DarwinAbiError(RewindError):
    """The Darwin statfs layout does not match the required ABI."""


class JournalError(RewindError):
    """The journal could not be opened or updated."""


class StateTransitionError(JournalError):
    """A conditional state change did not apply.

    The fencing check and the ``UPDATE ... WHERE state = expected`` run in one
    transaction. Zero rows means the transition is refused and no event is
    appended.
    """


class JournalCorruptionError(JournalError):
    """An existing database does not match the canonical schema.

    Damaged databases are never deleted or recreated automatically.
    """


class SchemaDefinitionError(JournalError):
    """The packaged schema does not match the phase 1 inventory."""


class LeaseBusyError(JournalError):
    """Another process holds the single-writer lock."""


class LeaseError(JournalError):
    """The lock file could not be acquired or no longer matches its descriptor."""


class FencingError(JournalError):
    """The write transaction failed the in-transaction fence check."""


class InjectedDDLFailure(JournalError):
    """A test hook aborted schema bootstrap at a chosen statement."""

    def __init__(self, index: int) -> None:
        super().__init__(f"injected DDL failure at statement {index}")
        self.index = index


class ContractError(RewindError):
    """A contract file or a call failed contract validation."""


class JsonLogicError(ContractError):
    """A JSON logic expression is invalid or cannot be evaluated safely."""


class JsonPathError(ContractError):
    """A redaction path is outside the approved grammar."""
