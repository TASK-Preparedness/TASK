#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Regenerate the Meshtastic *_pb2.py files from the .proto sources in this folder and
compare their serialized descriptors with the ones inside the bundled meshtastic wheel.

Same steps as meshtastic/python bin/regen-protobufs.sh at tag 2.7.11 (see regen-tools/),
without the mypy .pyi output. Needs protoc: ``pip install grpcio-tools``.

    python3 verify_descriptors.py ../vendor/meshtastic-2.7.11-py3-none-any.whl

Exit 0 only if every serialized descriptor is byte-identical. Not used at run time and
not part of any Debian package.
"""
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ADD = re.compile(r"AddSerializedFile\((b'(?:[^'\\]|\\.)*'|b\"(?:[^\"\\]|\\.)*\")\)")


def descriptor_bytes(text: str):
    m = ADD.search(text)
    return eval(m.group(1)) if m else None  # a bytes literal from a generated file we just built/extracted


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    wheel = Path(sys.argv[1])
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        inp = tmp / "in/meshtastic/protobuf"
        out = tmp / "out"
        inp.mkdir(parents=True)
        out.mkdir()
        for f in list((HERE / "meshtastic").glob("*.proto")) + list((HERE / "meshtastic").glob("*.options")):
            shutil.copy(f, inp / f.name)
        shutil.copy(HERE / "nanopb.proto", inp / "nanopb.proto")
        for f in inp.glob("*.proto"):
            t = f.read_text()
            t = re.sub(r"^package meshtastic;", "package meshtastic.protobuf;", t, flags=re.M)
            t = re.sub(r'^import "meshtastic/', 'import "meshtastic/protobuf/', t, flags=re.M)
            t = re.sub(r'^import "nanopb.proto"', 'import "meshtastic/protobuf/nanopb.proto"', t, flags=re.M)
            f.write_text(t)
        for opt in inp.glob("*.options"):
            proto = inp / (opt.stem + ".proto")
            if proto.exists():
                subprocess.run([sys.executable, str(HERE / "regen-tools/inject_nanopb_options.py.txt"), str(opt), str(proto)],
                               check=True, stdout=subprocess.DEVNULL)
        subprocess.run([sys.executable, "-m", "grpc_tools.protoc", f"-I={tmp / 'in'}", f"--python_out={out}",
                        *sorted(str(p) for p in inp.glob("*.proto"))], check=True)
        regenerated = {p.name: p.read_text() for p in (out / "meshtastic/protobuf").glob("*_pb2.py")}
        same, bad = 0, []
        with zipfile.ZipFile(wheel) as z:
            wanted = sorted(n for n in z.namelist() if n.startswith("meshtastic/protobuf/") and n.endswith("_pb2.py"))
            for n in wanted:
                name = Path(n).name
                a = descriptor_bytes(z.read(n).decode())
                b = descriptor_bytes(regenerated.get(name, ""))
                if a is not None and a == b:
                    same += 1
                else:
                    bad.append(name)
        extra = sorted(set(regenerated) - {Path(n).name for n in wanted})
        print(f"wheel pb2 files: {len(wanted)}; identical serialized descriptors: {same}; "
              f"different or missing: {bad or 'none'}; generated but not in wheel: {extra or 'none'}")
        return 0 if not bad and not extra and same == len(wanted) else 1


if __name__ == "__main__":
    raise SystemExit(main())
