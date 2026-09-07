"""Install the exact upstream source archive. Run during image build only."""
import argparse
import hashlib
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

COMMIT='3887ae68a6a6b8bb7b41d1b61998f1aa184201e4'
ARCHIVE_SHA256='31cf73ee4376d489466b4e34d9c82be9a42ddced5091417889f178d5ae671e33'

def main():
    p=argparse.ArgumentParser();p.add_argument('destination',type=Path);args=p.parse_args()
    if args.destination.exists():
        raise SystemExit('destination_must_not_exist')
    with tempfile.TemporaryDirectory() as td:
        archive=Path(td)/'source.tgz'
        urllib.request.urlretrieve(f'https://codeload.github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/tar.gz/{COMMIT}',archive)
        with archive.open('rb') as f:
            if hashlib.file_digest(f,'sha256').hexdigest()!=ARCHIVE_SHA256:
                raise SystemExit('upstream_archive_digest_mismatch')
        with tarfile.open(archive) as t:
            t.extractall(td,filter='data')
        root=Path(td)/('PathOfBuilding-PoE2-'+COMMIT)
        args.destination.mkdir(parents=True)
        for name in ('src','runtime/lua'):
            shutil.copytree(root/name,args.destination/name)
        for file in root.glob('LICENSE*'):
            shutil.copy2(file,args.destination/file.name)
        (args.destination/'COMPANION_COMMIT').write_text(COMMIT+'\n')
    print('pinned_engine_installed')

if __name__=='__main__':main()
