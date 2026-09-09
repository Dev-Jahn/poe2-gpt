"""Internal import/export primitives for private services and synthetic tests.

No public CLI or operator file-transfer workflow. Never send raw data to MCP.
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

from .builds import (BASE_CLASSES, STAT_NAMES, OPTIONAL_DERIVED_STAT_NAMES, UnavailableSavedStat, MAX_PROJECTION_BYTES, BuildError, BuildSummary,
                     Counts, PlayerStat, Projection, TreeSpec, ProjectedEquipmentItem,
                     EquipmentProperty, EquipmentModifier, bounded_dto, check_id, read_regular_file)

MAX_CODE_BYTES = 2 * 1024 * 1024
MAX_XML_BYTES = 8 * 1024 * 1024
MAX_XML_NODES = 100000

SLOT_MAP = {"Helmet":"helmet", "Body Armour":"body_armour", "Gloves":"gloves", "Boots":"boots",
    "Belt":"belt", "Amulet":"amulet", "Ring 1":"ring_left", "Ring 2":"ring_right",
    "Ring 3":"ring_third", "Weapon 1":"weapon_main", "Weapon 2":"weapon_off",
    "Flask 1":"flask_1", "Flask 2":"flask_2", "Charm 1":"charm_1", "Charm 2":"charm_2",
    "Charm 3":"charm_3", "Arm 1":"arm_1", "Arm 2":"arm_2", "Leg 1":"leg_1", "Leg 2":"leg_2"}
PROPERTY_NAMES = {"Armour", "Evasion", "Evasion Rating", "Energy Shield", "Ward", "Runic Ward", "Physical Damage",
    "Elemental Damage", "Critical Hit Chance", "Attacks per Second", "Chance to Block", "Spirit", "Radius"}


def safe_item_line(value, maximum=240):
    value = value.strip()
    if not value or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise BuildError("invalid_item_projection")
    return value


def numeric_property(line, prefix, minimum, maximum):
    if not line.startswith(prefix):
        return None
    raw = line[len(prefix):].strip().removesuffix("%")
    if not re.fullmatch(r"[+-]?\d{1,4}", raw):
        raise BuildError("invalid_item_projection")
    value = int(raw)
    if not minimum <= value <= maximum:
        raise BuildError("invalid_item_projection")
    return value


def parse_item_text(text, slot, saved_item_id):
    if not isinstance(text, str) or len(text.encode("utf-8")) > 32768:
        raise BuildError("invalid_item_projection")
    lines = [safe_item_line(line) for line in text.splitlines() if line.strip() and line.strip() != "--------"]
    if not lines or not lines[0].lower().startswith("rarity:") or len(lines) > 128:
        raise BuildError("invalid_item_projection")
    raw_rarity = lines[0].split(":", 1)[1].strip().lower()
    rarity = raw_rarity if raw_rarity in {"normal", "magic", "rare", "unique"} else "other"
    header = 2 if rarity in {"rare", "unique"} else 1
    if len(lines) <= header:
        raise BuildError("invalid_item_projection")
    name = None if rarity == "normal" else safe_item_line(lines[1], 160)
    base_type = safe_item_line(lines[header], 160)
    item_level = quality = level_requirement = socket_count = None
    corrupted = False
    properties, modifiers = [], []
    modifier_count, implicit_left = 0, 0
    truncated = False
    for line in lines[header+1:]:
        if line.startswith(("Unique ID:", "League:", "Prefix:", "Suffix:", "Crafted:",
                            "Variant:", "Selected Variant:", "Version:", "Selected Version:",
                            "Selected Variant Group:", "Has Alt Variant", "Selected Alt Variant",
                            "Allow Duplicate Variants:", "Unreleased:")):
            continue
        value = numeric_property(line, "Item Level:", 0, 100)
        if value is not None:
            item_level = value; continue
        value = numeric_property(line, "Quality:", -100, 100)
        if value is not None:
            quality = value; continue
        value = numeric_property(line, "LevelReq:", 0, 100)
        if value is not None:
            level_requirement = value; continue
        value = numeric_property(line, "Implicits:", 0, 32)
        if value is not None:
            implicit_left = value; continue
        if line == "Corrupted":
            corrupted = True; continue
        if line.startswith("Sockets:"):
            raw_sockets = line.split(":", 1)[1].strip()
            if raw_sockets and not re.fullmatch(r"[A-Za-z](?:[ -][A-Za-z])*", raw_sockets):
                raise BuildError("invalid_item_projection")
            socket_count = len(re.findall(r"[A-Za-z]", raw_sockets))
            if socket_count > 16:
                raise BuildError("invalid_item_projection")
            continue
        implicit = implicit_left > 0
        if implicit:
            implicit_left -= 1
        if line.startswith("Rune:"):
            kind = "rune"
        elif line.startswith("{rune}"):
            kind = "rune"; line = line[len("{rune}"):].strip()
        elif line.startswith("{crafted}"):
            kind = "crafted"; line = line[len("{crafted}"):].strip()
        elif line.startswith("{fractured}"):
            kind = "fractured"; line = line[len("{fractured}"):].strip()
        elif line.startswith("{enchant}"):
            kind = "enchant"; line = line[len("{enchant}"):].strip()
        elif implicit:
            kind = "implicit"
        elif ":" in line and line.split(":", 1)[0] in PROPERTY_NAMES:
            key, value = line.split(":", 1)
            if len(properties) < 24:
                properties.append(EquipmentProperty(name=key, value=safe_item_line(value, 160)))
            continue
        else:
            kind = "explicit"
        modifier_count += 1
        if len(modifiers) < 32:
            modifiers.append(EquipmentModifier(text=safe_item_line(line), kind=kind))
        else:
            truncated = True
    if implicit_left:
        raise BuildError("invalid_item_projection")
    return ProjectedEquipmentItem(slot=slot, saved_item_id=saved_item_id, rarity=rarity,
        name=name, base_type=base_type, item_level=item_level, quality=quality,
        level_requirement=level_requirement, corrupted=corrupted, socket_count=socket_count,
        properties=properties, modifiers=modifiers, modifier_count=modifier_count,
        modifiers_truncated=truncated)


def project_equipment(root):
    items = root.find("Items")
    if items is None:
        return []
    active = items.get("activeItemSet", "1")
    sets = [v for v in items.findall("ItemSet") if v.get("id") == active]
    if len(sets) != 1:
        return []
    item_set = sets[0]
    second = item_set.get("useSecondWeaponSet", items.get("useSecondWeaponSet", "false")) in {"true", "1"}
    by_id = {}
    for item in items.findall("Item"):
        raw_id = item.get("id", "")
        if not re.fullmatch(r"\d{1,7}", raw_id):
            raise BuildError("invalid_item_projection")
        item_id = int(raw_id)
        if item_id in by_id or not 1 <= item_id <= 1000000:
            raise BuildError("invalid_item_projection")
        by_id[item_id] = item.text or ""
    projected = []
    seen = set()
    for slot in item_set.findall("Slot"):
        name = slot.get("name", "")
        if name in {"Weapon 1", "Weapon 2"} and second:
            continue
        if name in {"Weapon 1 Swap", "Weapon 2 Swap"}:
            if not second:
                continue
            name = name.removesuffix(" Swap")
        canonical = SLOT_MAP.get(name)
        raw_id = slot.get("itemId", "0")
        if canonical is None or raw_id == "0":
            continue
        if canonical in seen or not re.fullmatch(r"\d{1,7}", raw_id) or int(raw_id) not in by_id:
            raise BuildError("invalid_item_projection")
        seen.add(canonical)
        projected.append(parse_item_text(by_id[int(raw_id)], canonical, int(raw_id)))
    return projected


def decode_pob(code: bytes) -> bytes:
    if len(code) > MAX_CODE_BYTES:
        raise BuildError("input_too_large")
    # Strip ASCII whitespace only. Do not accept URLs, pasted chat, or XML as code.
    normalized = b"".join(code.removeprefix(b"\xef\xbb\xbf").split())
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


def project_pob(xml: bytes, build_id: str, *, equipment_source=None) -> Projection:
    check_id(build_id)
    if equipment_source not in (None, "poe.ninja"):
        raise BuildError("invalid_item_projection")
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
    stats, unavailable, seen = [], [], set()
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
            if name in OPTIONAL_DERIVED_STAT_NAMES:
                # Immunity can produce an infinite maximum-hit estimate. Keep
                # the original and the rest of the build; never invent a finite
                # substitute or put nonstandard NaN/Infinity tokens into JSON.
                unavailable.append(UnavailableSavedStat(name=name,
                    reason='non_finite' if not math.isfinite(value) else 'outside_numeric_range'))
                continue
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
            stats=stats, unavailable_stats=unavailable, counts=Counts(saved_items=len(root.findall("./Items/Item")),
            saved_skill_groups=len(root.findall("./Skills/Skill"))+len(root.findall("./Skills/SkillSet/Skill")),
            saved_gems=len(root.findall("./Skills/Skill/Gem"))+len(root.findall("./Skills/SkillSet/Skill/Gem")),
            saved_tree_specs=len(trees))))
        # Optional legacy display projection must never prevent native worker
        # inspection/import of a valid PoB with complex variants or item text.
        legacy_equipment=[]
        if equipment_source == 'poe.ninja':
            try:
                legacy_equipment=project_equipment(root)
            except (BuildError, ValidationError):
                pass
        return Projection(equipment_projection_version=1 if equipment_source == "poe.ninja" else None,
            equipment_source=equipment_source, summary=summary, trees=trees,
            equipment=legacy_equipment)
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


def import_file(source: Path, private_dir: Path, projection_dir: Path, *, equipment_source=None) -> str:
    validate_roots(private_dir, projection_dir)
    code = read_regular_file(source, MAX_CODE_BYTES)
    build_id = "bld_" + secrets.token_hex(16)
    projection = project_pob(decode_pob(code), build_id, equipment_source=equipment_source)
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


def import_stream(stream, private_dir: Path, projection_dir: Path, *, equipment_source=None) -> str:
    """Operator terminal pipe, never an MCP input. Bound and remove staging data."""
    code = stream.read(MAX_CODE_BYTES + 1)
    if len(code) > MAX_CODE_BYTES:
        raise BuildError("input_too_large")
    with tempfile.TemporaryDirectory(prefix="poe2-import-") as temporary:
        source = Path(temporary) / "input.pob"
        atomic_write(source, code)
        return import_file(source, private_dir, projection_dir, equipment_source=equipment_source)


def export_file(build_id: str, private_dir: Path, destination: Path):
    check_id(build_id)
    code = read_regular_file(private_dir / (build_id + ".pob"), MAX_CODE_BYTES)
    # Exclusive creation: never overwrite another file or follow a target symlink.
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(code)


class PrivateArgumentParser(argparse.ArgumentParser):
    """Shared safe diagnostics for the separate equipment snapshot utility."""
    def error(self, message):
        self.exit(2, '{"status": "failed", "code": "invalid_cli_arguments"}\n')
