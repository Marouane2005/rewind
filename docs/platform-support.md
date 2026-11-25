# Platform support

| Host | Journal filesystem | Status in this tree |
| --- | --- | --- |
| Linux x86_64 | ext2, ext3, ext4, xfs, btrfs, zfs, f2fs, jfs, reiserfs | Implemented. Live checks run where the host is Linux. |
| Linux other architectures | same allowlist | The code is not architecture-specific. It has not been executed on non-x86_64 Linux in the initial run. |
| macOS arm64 | apfs, hfs, ufs, zfs | Implemented. Live `fstatfs` runs only on Darwin. |
| macOS x86_64 | apfs, hfs, ufs, zfs | Same code path. Not verified until a live x86_64 Darwin run passes. |
| Windows | none | `UnsupportedPlatformError` |
| 32-bit Darwin | none | `UnsupportedPlatformError` |

`tmpfs` is allowed on Linux and macOS only with `--allow-tmpfs`.

## Linux

The database directory is resolved with `os.path.realpath`. If it does not exist, the check walks up to the deepest existing ancestor. That directory is opened with `O_PATH | O_DIRECTORY | O_CLOEXEC`. There is no `O_RDONLY` fallback. If `os.O_PATH` is missing, validation fails.

`mnt_id` is read from `/proc/self/fdinfo/<fd>`. `/proc/self/mountinfo` is parsed in `resolve_linux_mount`. The directory's mount id selects the entry. Longest path-prefix matching is not used, so an overmount is not mistaken for a hidden descendant filesystem.

Mount ids must be positive and unique. `parent_id` may be 0 because some kernels use 0 for the namespace root. Negative parent ids, malformed escapes, and incomplete lines fail closed. Only `\040`, `\011`, `\012`, and `\134` are unescaped, and only once.

## macOS

Darwin uses `fstatfs` through `ctypes` and never reads `/proc` or runs `df`. The structure is `__DARWIN_STRUCT_STATFS64` from XNU `bsd/sys/mount.h` at tag `xnu-11215.81.4` (https://github.com/apple-oss-distributions/xnu/blob/xnu-11215.81.4/bsd/sys/mount.h). On 64-bit Darwin that macro is `struct statfs`, and `fstatfs` is the `__DARWIN_INODE64` entry. `MAXPATHLEN` is `PATH_MAX` (`bsd/sys/param.h`); Darwin defines `PATH_MAX` as 1024. The resulting LP64 layout is 2168 bytes, with `f_fstypename` at 72, `f_mntonname` at 88, `f_mntfromname` at 1112, `f_flags_ext` at 2136, and `f_reserved` at 2140. If ctypes does not produce that layout, `DarwinAbiError` is raised and the layout is not edited at runtime.

Names are taken from the fixed buffers only when a NUL is present, and they are decoded as strict UTF-8. The descriptor is closed on success and on failure.

The layout was not compared with an Apple SDK on the Linux host that produced the initial test run. A later macOS CI job, if it passes, verifies the architecture of that runner only.

## Reporting

`rewind fs check PATH` prints the system, machine, bit width, and filesystem type it resolved. `rewind report schema` includes the same filesystem type after the journal is open.
