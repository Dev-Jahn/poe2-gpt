"""Validate the public package contract using only the Python standard library."""
from pathlib import Path
import json
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def main():
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
    manifest = json.loads((ROOT / '.codex-plugin/plugin.json').read_text())
    assert project['name'] == manifest['name'] == 'poe2-gpt'
    assert project['version'] == manifest['version']
    source_version = re.search(r'^__version__ = "([0-9.]+)"$',
        (ROOT / 'src/poe2_companion/__init__.py').read_text(), re.MULTILINE)
    assert source_version and source_version[1] == project['version']
    assert manifest['license'] == 'MIT'
    assert manifest['mcpServers'] == './.mcp.json'
    config = json.loads((ROOT / '.mcp.json').read_text())
    assert config == {'mcpServers': {'poe2-gpt': {'command': 'poe2-gpt', 'args': ['--transport', 'stdio']}}}
    catalog = json.loads((ROOT / '.agents/plugins/marketplace.json').read_text())
    entry = catalog['plugins'][0]
    assert entry['name'] == manifest['name']
    assert entry['source']['url'] == project['urls']['Repository'] + '.git'
    assert entry['source']['source'] == 'url'
    for name in ('README.md','README.ko.md','README.de.md','README.ru.md','README.pt-BR.md'):
        text = (ROOT / name).read_text()
        assert project['version'] in text and '38' in text and '17' in text, name
        assert 'indeterminate' in text and '20' in text and '75' in text, name
    for path in [*ROOT.glob('*.md'), *ROOT.glob('docs/*.md')]:
        for target in re.findall(r'\]\(([^)\s]+)\)', path.read_text()):
            if '://' in target or target.startswith('#'):
                continue
            destination = (path.parent / target.split('#')[0]).resolve()
            assert destination.is_relative_to(ROOT) and destination.exists(), (path.name, target)
    for name in ('LICENSE','NOTICE','SECURITY.md','CONTRIBUTING.md','CHANGELOG.md'):
        assert (ROOT / name).is_file(), name
    assert not (ROOT / '.app.json').exists(), 'Do not publish account-specific mappings'
    for path in [*ROOT.glob('src/**/*.py'), *ROOT.glob('scripts/*.py')]:
        compile(path.read_text(), str(path), 'exec')
    print('Public package metadata, local documentation links, locales, and Python syntax: OK')


if __name__ == '__main__':
    main()
