"""Build checksum-pinned LuaJIT and luautf8 during Docker build."""
import hashlib
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

LUAJIT_COMMIT='24c20c94e7db195b640854619577441f9b4bc6be'
ARCHIVES=[
 ('LuaJIT/LuaJIT',LUAJIT_COMMIT,'178c656b62bb796e536a23f1d3bb09e1824e4dd28eaf2a4758b295ac328e32e6'),
 ('starwing/luautf8','0.2.0','f79c11d994b86864f5c6c5326dcaede2b10c37303d664c1010705c3d2e23b232'),
]
with tempfile.TemporaryDirectory() as td:
    roots=[]
    for repo,ref,digest in ARCHIVES:
        file=Path(td)/(repo.split('/')[1]+'.tgz')
        urllib.request.urlretrieve(f'https://codeload.github.com/{repo}/tar.gz/{ref}',file)
        with file.open('rb') as f:
            if hashlib.file_digest(f,'sha256').hexdigest()!=digest:raise SystemExit('runtime_digest_mismatch')
        with tarfile.open(file) as t:
            root=Path(td)/t.getmembers()[0].name.split('/')[0]
            t.extractall(td,filter='data');roots.append(root)
    subprocess.run(['make','-C',str(roots[0]),'-j2'],check=True)
    subprocess.run(['make','-C',str(roots[0]),'install','PREFIX=/opt/lua'],check=True)
    target=Path('/opt/lua/lib/lua/5.1');target.mkdir(parents=True,exist_ok=True)
    subprocess.run(['cc','-O2','-fPIC','-shared','-I'+str(roots[0]/'src'),'-o',str(target/'lua-utf8.so'),str(roots[1]/'lutf8lib.c')],check=True)
    for root in roots:
        for file in list(root.glob('COPYRIGHT'))+list(root.glob('LICENSE*')):
            dest=Path('/opt/lua/licenses')/root.name;dest.mkdir(parents=True,exist_ok=True);shutil.copy2(file,dest/file.name)
