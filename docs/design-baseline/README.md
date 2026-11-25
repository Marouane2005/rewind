# REWIND — Phase 0.3 Reference Pack

This folder contains a **reconstructed written baseline** based on the architectural decisions discussed so far.

Important:
- This is not an original source-code snapshot.
- No original Phase 0.3 repository or implementation files were supplied.
- Do not treat missing source files as implemented or tested.
- Keep this folder unchanged once accepted as the reference baseline.
- Phase 1 implementation belongs in the main project source tree, not inside this reference folder.

Read in this order:
1. `PHASE_0.3_BASELINE.md`
2. `ARCHITECTURE_DECISIONS.md`
3. `PHASE_1_SCOPE_AND_ACCEPTANCE.md`
4. `COMMERCIAL_PRODUCT_MISSION.md`
5. `FILE_INVENTORY.md`

The implementation must inspect the actual repository before making changes and must clearly distinguish:
- facts established by this pack,
- facts discovered in the repository,
- assumptions requiring confirmation.

## Repository state supplied by the owner

The owner has explicitly confirmed that there are no pre-existing project files other than the files in this generated pack. Therefore:
- there is no original Phase 0.3 source-code implementation to recover;
- there is no pre-existing `pyproject.toml`, `schema.sql`, proxy source, or executable test suite;
- this pack is the written starting specification, not evidence of a previous implementation;
- The implementation must treat the implementation as a clean project bootstrap and must not report a pre-existing test baseline.
