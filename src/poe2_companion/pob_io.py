"""Operator-only file import/export, intentionally absent from MCP tools.

Run on the homelab directly. Never send code as command-line arguments,
stdout, MCP fields, resources, or model-visible metadata.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import math
import os
import re
import secrets
import sys
import tempfile
import time
import zlib
from pathlib import Path

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from pydantic import ValidationError
from xml.etree.ElementTree import ParseError

from .builds import (BASE_CLASSES, STAT_NAMES, MAX_PROJECTION_BYTES, BuildError, BuildSummary,
                     Counts, PlayerStat, Projection, TreeSpec, bounded_dto, check_id, read_regular_file)

MAX_CODE_BYTES = 2 * 1024 * 1024
MAX_XML_BYTES = 8 * 1024 * 1024
MAX_XML_NODES = 100000


def decode_pob(code: bytes) -> bytes:
    if len(code) > MAX_CODE_BYTES:
        raise BuildError("input_too_large")
    # Strip ASCII whitespace only. Do not accept URLs, pasted chat, or XML as code.
    normalized = b"".join(code.split())
    if not normalized or not re.fullmatch(rb"[A-Za-z0-9_+/\-]+={0,2}", normalized):
        raise BuildError("invalid_pob_code")
    try:
        compressed = base64.b64decode(normalized + b"=" * (-len(normalized) % 4), altchars=b"-_", validate=True)
        decoder = zlib.decompressobj()
        xml = decoder.decompress(compressed, MAX_XML_BYTES + 1)
        if len(xml) > MAX_XML_BYTES or decoder.unconsumed_tail:
            raise BuildError("expanded_pob_too_large")
        if not decoder.eof or decoder.unused_data:
            raise BuildError("invalid_pob_stream")
        return xml
    except (binascii.Error, zlib.error, ValueError):
        raise BuildError("invalid_pob_code") from None


def int_field(raw: str, minimum: int, maximum: int) -> int:
    if not re.fullmatch(r"\d{1,10}", raw):
        raise BuildError("invalid_numeric_field")
    value = int(raw)
    if not minimum <= value <= maximum:
        raise BuildError("invalid_numeric_field")
    return value


def project_pob(xml: bytes, build_id: str) -> Projection:
    check_id(build_id)
    if len(xml) > MAX_XML_BYTES:
        raise BuildError("expanded_pob_too_large")
    try:
        root = ElementTree.fromstring(xml, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (DefusedXmlException, ParseError, ValueError):
        raise BuildError("invalid_pob_xml") from None
    if root.tag != "PathOfBuilding2":
        raise BuildError("unsupported_pob_game")
    stack, count = [(root, 0)], 0
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > MAX_XML_NODES or depth > 64:
            raise BuildError("pob_structure_too_large")
        stack.extend((child, depth+1) for child in node)
    builds = root.findall("Build")
    if len(builds) != 1:
        raise BuildError("invalid_build_section")
    build = builds[0]
    class_name = build.get("className", "Unknown")
    # Only a closed enum crosses the boundary; arbitrary labels do not.
    if class_name not in BASE_CLASSES:
        class_name = "Unknown"
    version = build.get("targetVersion", "")
    version = [int(v) for v in re.split(r"[._]", version)] if re.fullmatch(r"\d{1,3}(?:[._]\d{1,3}){0,3}", version) else None
    stats, seen = [], set()
    for stat_node in build.findall("PlayerStat"):
        name = stat_node.get("stat")
        if name not in STAT_NAMES:
            continue
        if name in seen:
            raise BuildError("duplicate_player_stat")
        seen.add(name)
        raw = stat_node.get("value", "")
        if len(raw) > 32:
            raise BuildError("invalid_numeric_field")
        try:
            value = float(raw)
        except ValueError:
            raise BuildError("invalid_numeric_field") from None
        if not math.isfinite(value) or abs(value) > 1e15:
            raise BuildError("invalid_numeric_field")
        stats.append(PlayerStat(name=name, value=value))
    tree_nodes = root.findall("./Tree/Spec")
    if len(tree_nodes) > 100:
        raise BuildError("pob_structure_too_large")
    trees = []
    for index, spec in enumerate(tree_nodes):
        raw_nodes = spec.get("nodes", "")
        values = raw_nodes.split(",") if raw_nodes else []
        if len(values) > 2000:
            raise BuildError("pob_structure_too_large")
        trees.append(TreeSpec(index=index, node_ids=sorted(set(int_field(v, 0, 2147483647) for v in values))))
    try:
        summary = bounded_dto(BuildSummary(build_id=build_id, imported_at_epoch=int(time.time()),
            class_name=class_name, level=int_field(build.get("level", ""), 1, 100), target_version=version,
            stats=stats, counts=Counts(saved_items=len(root.findall("./Items/Item")),
            saved_skill_groups=len(root.findall("./Skills/Skill"))+len(root.findall("./Skills/SkillSet/Skill")),
            saved_gems=len(root.findall("./Skills/Skill/Gem"))+len(root.findall("./Skills/SkillSet/Skill/Gem")),
            saved_tree_specs=len(trees))))
        return Projection(summary=summary, trees=trees)
    except ValidationError:
        raise BuildError("invalid_build_projection") from None


def atomic_write(path: Path, data: bytes, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".import-")
    try:
        with os.fdopen(fd, "wb") as file:
            os.fchmod(file.fileno(), mode) if hasattr(os, "fchmod") else None
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_roots(private_dir: Path, projection_dir: Path):
    private_dir, projection_dir = private_dir.resolve(), projection_dir.resolve()
    if private_dir == projection_dir or private_dir in projection_dir.parents or projection_dir in private_dir.parents:
        raise BuildError("raw_and_projection_roots_must_be_separate")


def import_file(source: Path, private_dir: Path, projection_dir: Path) -> str:
    validate_roots(private_dir, projection_dir)
    code = read_regular_file(source, MAX_CODE_BYTES)
    build_id = "bld_" + secrets.token_hex(16)
    projection = project_pob(decode_pob(code), build_id)
    data = projection.model_dump_json().encode("utf-8")
    if len(data) > MAX_PROJECTION_BYTES:
        raise BuildError("projection_too_large")
    # Raw is stored separately and never included in model projections.
    raw_path = private_dir / (build_id + ".pob")
    atomic_write(raw_path, code)
    try:
        atomic_write(projection_dir / (build_id + ".json"), data)
    except BaseException:
        raw_path.unlink(missing_ok=True)
        raise
    return build_id


def import_stream(stream, private_dir: Path, projection_dir: Path) -> str:
    """Operator terminal pipe, never an MCP input. Bound and remove staging data."""
    code = stream.read(MAX_CODE_BYTES + 1)
    if len(code) > MAX_CODE_BYTES:
        raise BuildError("input_too_large")
    with tempfile.TemporaryDirectory(prefix="poe2-import-") as temporary:
        source = Path(temporary) / "input.pob"
        atomic_write(source, code)
        return import_file(source, private_dir, projection_dir)


def export_file(build_id: str, private_dir: Path, destination: Path):
    check_id(build_id)
    code = read_regular_file(private_dir / (build_id + ".pob"), MAX_CODE_BYTES)
    # Exclusive creation: never overwrite another file or follow a target symlink.
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(code)


class PrivateArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes invalid values/unknown arguments. A mistaken
        # pasted payload must not be copied into diagnostics or captured logs.
        self.exit(2, '{"status": "failed", "code": "invalid_cli_arguments"}\n')


def main():
    parser = PrivateArgumentParser(description="Local operator PoB file import/export. Never run via model tools.")
    commands = parser.add_subparsers(dest="command", required=True)
    load = commands.add_parser("import")
    input_group = load.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input", type=Path)
    input_group.add_argument("--stdin", action="store_true", help="Read a bounded operator-only pipe")
    load.add_argument("--private-dir", required=True, type=Path)
    load.add_argument("--projection-dir", required=True, type=Path)
    save = commands.add_parser("export")
    save.add_argument("--build-id", required=True)
    save.add_argument("--private-dir", required=True, type=Path)
    save.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "import":
            build_id = (import_stream(sys.stdin.buffer, args.private_dir, args.projection_dir)
                        if args.stdin else import_file(args.input, args.private_dir, args.projection_dir))
            print(json.dumps({"status": "imported", "build_id": build_id}))
        else:
            export_file(args.build_id, args.private_dir, args.output)
            print(json.dumps({"status": "exported", "build_id": args.build_id}))
    except BuildError as exc:
        print(json.dumps({"status": "failed", "code": str(exc)}), file=sys.stderr)
        sys.exit(1)
    except (OSError, ValidationError, ValueError, RecursionError):
        print(json.dumps({"status": "failed", "code": "pob_operation_failed"}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
