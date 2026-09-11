"""Check the public 79-case test map, without treating a mapping as a pass."""
import ast,json
from pathlib import Path


def check(root: Path) -> None:
    value=json.loads((root/'docs/workflow-014-cases.json').read_text())
    counts={i:4 if i in {7,8,9,13} else 3 for i in range(1,26)}
    expected={f'MCP-{issue:03d}-T{case:02d}' for issue,count in counts.items() for case in range(1,count+1)}
    rows=value['cases'];assert len(rows)==79 and {r['case_id'] for r in rows}==expected
    assert value['mapping_is_not_a_test_pass'] is True
    for row in rows:
        assert row['tests'] and row['historical_private_fixture_replayed'] is False
        for selector in row['tests']:
            path,name=selector.split('::');target=(root/path).resolve()
            assert target.is_relative_to(root/'tests') and target.is_file(),selector
            names={n.name for n in ast.parse(target.read_text()).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
            assert name in names,selector
    print('All 25 tickets / 79 cases map to existing executable tests; execution remains a separate gate.')


if __name__=='__main__':check(Path(__file__).resolve().parents[1])
