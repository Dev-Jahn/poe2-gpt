"""CI gate: run the complete suite and require actual engine coverage."""
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
import pytest

with tempfile.TemporaryDirectory(prefix="poe2-tests-") as directory:
    report = Path(directory) / "results.xml"
    result = pytest.main(["-q", f"--junitxml={report}"])
    if result:
        raise SystemExit(result)
    root = ET.parse(report).getroot()
    if any(int(suite.get("skipped", "0")) for suite in root.iter("testsuite")):
        raise SystemExit("Real-engine CI must not skip tests")
