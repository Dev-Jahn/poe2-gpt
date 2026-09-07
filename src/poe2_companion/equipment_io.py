"""Operator-only import of structured equipment snapshots; never a PoB input."""
from __future__ import annotations

import json
import secrets
import sys
import time
from pathlib import Path

from pydantic import ValidationError

from .builds import BuildError, read_regular_file
from .equipment import Dataset, EquipmentInput, MAX_DATASET_BYTES
from .pob_io import PrivateArgumentParser, atomic_write


def import_equipment(source: Path, directory: Path, clock=time.time) -> str:
    try:
        data = EquipmentInput.model_validate_json(read_regular_file(source, MAX_DATASET_BYTES))
    except (ValidationError, ValueError, RecursionError):
        raise BuildError("invalid_equipment_input") from None
    now = int(clock())
    if any(c.observed_at_epoch > now+300 for c in data.candidates):
        raise BuildError("future_listing_timestamp")
    dataset_id = "gear_"+secrets.token_hex(16)
    stored = Dataset(**data.model_dump(), dataset_id=dataset_id, imported_at_epoch=now)
    body = stored.model_dump_json().encode()
    if len(body) > MAX_DATASET_BYTES:
        raise BuildError("equipment_snapshot_too_large")
    atomic_write(directory/(dataset_id+".json"), body)
    return dataset_id


def main():
    parser = PrivateArgumentParser(description="Import a typed equipment JSON snapshot outside ChatGPT. No PoB/XML/item text.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--projection-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        dataset_id = import_equipment(args.input, args.projection_dir)
        print(json.dumps({"status":"imported", "dataset_id":dataset_id}))
    except BuildError as exc:
        print(json.dumps({"status":"failed", "code":str(exc)}),file=sys.stderr)
        sys.exit(1)
    except (OSError, ValidationError, ValueError, RecursionError):
        print('{"status":"failed","code":"equipment_import_failed"}',file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
