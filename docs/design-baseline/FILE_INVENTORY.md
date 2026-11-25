# File Inventory and Missing Artifacts

## What this pack contains

This folder contains reconstructed written specifications and accompanying notes only.

## What it does not contain

It does not contain:
- the original Phase 0.3 Python source code;
- an original `schema.sql`;
- an original `pyproject.toml`;
- a verified original test suite;
- executable proxy implementation;
- proof that any requirement has already been implemented or tested.

## How the implementation must handle this

The implementation must inspect the actual repository and report which source files exist. If the repository is empty, the implementation must say so and treat Phase 1 as a new implementation based on the written specification.

The implementation must not fabricate an original Phase 0.3 implementation or claim that this pack is a source-code backup.

## Suggested future project structure

```text
REWIND/
├── reference/
│   └── phase-0.3/          # This frozen reference pack
├── src/
│   └── rewind/             # Actual implementation
├── tests/                  # Executable tests
├── contracts/              # Example/validated contracts, if applicable
├── docs/                   # User and developer documentation
├── pyproject.toml
└── README.md
```

This is a suggested structure, not an instruction to move existing files blindly.

## Owner-confirmed starting condition

The owner confirms that no other project files currently exist beyond the generated reference pack. Treat the repository as a clean slate. There is no existing implementation or test baseline to inspect. Create the initial project structure deliberately, and report the first test run as a newly established baseline rather than a regression comparison.
