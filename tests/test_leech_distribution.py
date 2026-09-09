import itertools
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


def test_mean_of_capped_hits_and_mixed_type_oracle():
    lua = os.environ.get('POE2_TEST_LUAJIT') or shutil.which('luajit')
    if not lua:
        pytest.skip('LuaJIT required for distribution oracle')
    module = Path(__file__).parents[1] / 'src/poe2_companion/lua/leech_distribution.lua'
    script = '''local m=dofile(os.getenv('POE2_LEECH_MODULE'))
print(m.capped_mean(20000,60000,40000,0,true)*0.1)
print(m.capped_mean(20000,60000,40000,1,true)*0.1)
print(m.capped_mean(20000,60000,40000,0,false)*0.1)
local l,n,e,x=m.integrate({{minimum=10000,maximum=50000,endpoints=true,lucky=0,life=0.1,mana=0,es=0},
{minimum=20000,maximum=60000,endpoints=true,lucky=0,life=0,mana=0.2,es=0}},40000)
print(l,n,e,x)
'''
    result = subprocess.run([lua, '-e', script], env={**os.environ,'POE2_LEECH_MODULE':str(module)}, capture_output=True, text=True, check=True)
    lines=result.stdout.splitlines()
    assert [float(v) for v in lines[:3]] == pytest.approx([3000,3500,3500])
    life=mana=0
    for physical,fire in itertools.product((10000,50000),(20000,60000)):
        scale=min(1,40000/(physical+fire))
        life+=.25*physical*.1*scale
        mana+=.25*fire*.2*scale
    values=lines[3].split()
    assert [float(v) for v in values[:3]] == pytest.approx([life,mana,0])
    assert values[3]=='true'
