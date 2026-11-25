# Meshtastic protobuf sources for the bundled `meshtastic` 2.7.11 wheel

**Documentation and source only. Nothing in this folder is installed, imported or
run by T.A.S.K., and none of it goes into a Debian package.** It exists so that
anyone who receives the `task-mesh` package also has the preferred form for
modification (the `.proto` files) of the generated `meshtastic/protobuf/*_pb2.py`
files that are inside the bundled wheel
`mesh/packaging/vendor/meshtastic-2.7.11-py3-none-any.whl`.

## Which revision

| Item | Value |
|---|---|
| Upstream repository | https://github.com/meshtastic/protobufs |
| Exact commit | `da60cee584c6dc1efbb4a3809b98666505179b85` (upstream tag `v2.7.26`) |
| How it was identified | It is the `protobufs` git submodule pointer of https://github.com/meshtastic/python at tag `2.7.11` (GitHub contents API: `repos/meshtastic/python/contents/protobufs?ref=2.7.11`). |
| Confirmed by | Regenerating all 25 `*_pb2.py` files from these sources and comparing them with the wheel: **25 of 25 serialized descriptors are byte-identical.** Run `verify_descriptors.py` yourself (below). |
| Why the match is specific | Upstream `master` has moved on (384 commits and 33 changed files since this commit), so the descriptors would not match a different revision. |
| Wheel | `meshtastic-2.7.11-py3-none-any.whl`, SHA-256 `adb020f2cd7ace53896c6bf487f2d2136498dd88052c41a2aa6fb7a4634971b5` (same value as on PyPI) |
| Licenses | `LICENSE` here is the upstream protobufs `LICENSE`, GNU GPL version 3 (byte-identical to this project's `LICENSE`). `regen-tools/LICENSE-meshtastic-python.md` is the license file of the meshtastic Python repository at tag 2.7.11 (GPL-3.0). |

## What is here

| Path | What it is | Origin |
|---|---|---|
| `meshtastic/*.proto`, `meshtastic/*.options` | The 24 protocol definition files and 19 nanopb `.options` files | meshtastic/protobufs @ `da60cee` (unmodified) |
| `nanopb.proto` | The nanopb field-option definitions that the others import | meshtastic/protobufs @ `da60cee` (unmodified; the file comes from the nanopb project) |
| `LICENSE`, `README.md`, `buf.yaml`, `buf.gen.yaml` | Upstream license, readme and buf configuration | meshtastic/protobufs @ `da60cee` (unmodified) |
| `regen-tools/regen-protobufs.sh.txt` | The generation script upstream used. Stored with a `.txt` suffix so that this repository's own `.py`/`.sh` license-header test does not treat a third-party file as T.A.S.K. code; the content is the unmodified `bin/regen-protobufs.sh` | meshtastic/python @ tag `2.7.11` (unmodified) |
| `regen-tools/inject_nanopb_options.py.txt` | Helper called by that script. Same `.txt` suffix reason; content is the unmodified `bin/inject_nanopb_options.py` | meshtastic/python @ tag `2.7.11` (unmodified) |
| `regen-tools/LICENSE-meshtastic-python.md` | License of the two files above | meshtastic/python @ tag `2.7.11`, `LICENSE.md` |
| `verify_descriptors.py` | T.A.S.K.'s check script (GPL-3.0-or-later) | this repository |

All upstream files are unmodified copies. This folder is **not** the project's
own code; it is third-party GPL-3.0 source redistributed for compliance.

## How the generated files are produced (upstream method)

Upstream runs `bin/regen-protobufs.sh` (kept in `regen-tools/` as `regen-protobufs.sh.txt`; drop the `.txt` to use it) from the root
of a checkout of meshtastic/python with the protobufs submodule at the commit
above. In short, for each `.proto` and `.options` file it:

1. copies `meshtastic/*.proto`, `meshtastic/*.options` and `nanopb.proto` into
   `meshtastic/protobuf/` in a temporary tree;
2. rewrites `package meshtastic;` to `package meshtastic.protobuf;` and prefixes
   the imports (`meshtastic/` and `nanopb.proto`) with `meshtastic/protobuf/`;
3. runs `inject_nanopb_options.py` to copy the `.options` limits into inline
   field options, so they appear in the descriptors;
4. runs `protoc --python_out` (upstream uses the `protoc` bundled with nanopb 0.4.8)
   and `--mypy_out` (mypy-protobuf, for the `.pyi` stubs);
5. changes `from meshtastic.protobuf import` to `from . import` in the output.

## Check it yourself

```
python3 -m venv /tmp/pbvenv && /tmp/pbvenv/bin/pip install grpcio-tools
cd mesh/packaging/vendor-source/meshtastic-protobufs-da60cee
/tmp/pbvenv/bin/python verify_descriptors.py ../../vendor/meshtastic-2.7.11-py3-none-any.whl
```

Expected output:
`wheel pb2 files: 25; identical serialized descriptors: 25; different or missing: none; generated but not in wheel: none`

`verify_descriptors.py` repeats steps 1 to 3 and 5 of the upstream method with
Python and calls `protoc` through `grpc_tools` (it skips the `.pyi` stubs). It
was run on 2026-11-25 with grpcio-tools 1.85.4 (libprotoc 35.1). A different
`protoc` writes different Python text, but the serialized descriptor, which is
what is compared, comes out identical.

## Not covered by this check

* The `.pyi` stub files and the exact text of the generated `.py` files are not
  compared byte for byte (they depend on the `protoc` and mypy-protobuf versions).
  The serialized descriptors, which carry all message, field and option data, are.
* I did not run upstream's script itself (it needs poetry and the nanopb 0.4.8
  bundle); `verify_descriptors.py` is an equivalent re-implementation.
* The Python source of the meshtastic library itself is inside the wheel, and
  the PyPI source distribution is `meshtastic-2.7.11.tar.gz`, SHA-256
  `41a8c84b577daff173d36db9fdbc8bf2c7228b58e580474e9f53802ed8ea7d4a`.
