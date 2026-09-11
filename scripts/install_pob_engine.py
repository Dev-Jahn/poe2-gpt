"""Install the exact upstream source archive. Run during image build only."""
import argparse
import concurrent.futures
import hashlib
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

COMMIT='fd4c1acb7f9f5ffd13372f5387ae16f8e6278c15'
ARCHIVE_SHA256='1f34fb7a0b35d6916e9e5d1dea79a16b57cc282225abf3a2f1fc0ed3deb80630'
DATA_COMMIT='b3282b7a9111ed6c4ec6be643edf0806d7beb675'
COMPATIBILITY='forbidden-rites-0.5.5-v5'
# Reviewed data-only subset of open upstream PR2505; no UI or executable
# module changes are imported from the PR. Every file is immutable and hashed.
DATA_FILES={
  "src/Data/Bases/belt.lua": "bfc0654ff1f1fe068866fb0dc892faeebb9ec36e87e365b10ec72f1d7091c3c5",
  "src/Data/Bases/sceptre.lua": "e4ced96a6064e6fbd447cb01edd1e0c482ab7d6d710b502764749c850c9fc8a4",
  "src/Data/Bases/staff.lua": "8589a6fe4c7f8c44261318f3e3212c7c563751372366ce5795b0a9b264b3620d",
  "src/Data/Bases/wand.lua": "83380d46933eca12a6df6308be0d1664f79fb70f841209e194e362f94af3d8a1",
  "src/Data/Gems.lua": "9c748de5622b2e52d90f15b13277d7d5440a69b673dd57042ead49c23072765a",
  "src/Data/LiquidEmotions.lua": "2f8783e2f3d26fabc2a58c9533ffe96461ae0343ab6b3a2037249c68d00da7a8",
  "src/Data/Minions.lua": "b56e141e6ee33c0781d82ba4b465961865496a4f610f82d788a4291aef036be9",
  "src/Data/ModCache.lua": "eef89cabdd26454cdde0c445567d937cf2d9176882fb653fe527ca4e5933ea98",
  "src/Data/ModCorrupted.lua": "50549cb0cbe722e28b337b30e4918e14ddf14bd4aa5da5d064984b1ba8f99351",
  "src/Data/ModIncursionLimb.lua": "a0d51bb464e1204e4930d3513b740be02fe9ab1d93716f571eeabb32ed22bfe9",
  "src/Data/ModItem.lua": "774257f577f8cee8ac59d7848df4bc7a109d266a615eb97c2a2c08ecb6b47cf4",
  "src/Data/ModItemExclusive.lua": "5a036d7f2a033e3073be25ded4a7aece45bf80046d477dd23b300285511d1d12",
  "src/Data/ModJewel.lua": "44285abc35fa4c32b2b0ba169570c99b01fd97136d1a801462b9b1398db82e80",
  "src/Data/ModRunes.lua": "d3dac48143209d7d9a02a8c03bd86f21604a0961a8ced49290d6a1d243f8223a",
  "src/Data/ModScalability.lua": "c0e4edaf1ea37c7bec331747f6a3bd91f21e32d302e4214a4512c790a58b1db9",
  "src/Data/ModVeiled.lua": "95234097bcb70946ad451fbdb80b93cff3bd4a57abfdf29052305905fd32a632",
  "src/Data/QueryMods.lua": "4dcfd15f75ace883b09e945492a34333e3ff497eddc848fb9061d42459318b6f",
  "src/Data/Skills/act_dex.lua": "4da51913bf22066af7be1a7a0ce5d3763adae18b5c5e0ff23ef1630da67762b6",
  "src/Data/Skills/act_int.lua": "da6cfd70e6e1335e48653b8a2d6574fe45da98909660cd7582b28dd37b7ae716",
  "src/Data/Skills/act_str.lua": "2860cae594d0c41cc9b77035011677c2ba02c8109acae230c516a2b74fa1e674",
  "src/Data/Skills/minion.lua": "56966a908ce91d5e1cc911f0bfd621e0d9a3ce91b0b18cb9fc7a3d52aab37ed2",
  "src/Data/Skills/other.lua": "0b78fa1417a40e3c42b48a87645791e42c83ce393d45eded0d1bb8ac250d8319",
  "src/Data/Skills/spectre.lua": "df1a23436d828317cb07ac69be5fb9124889f2f3107aa19e177fca24b44bfcc0",
  "src/Data/Skills/sup_dex.lua": "d47478e912b683b24b1ea92388f6c4a993f97038d4a18a49710a743394cabb5f",
  "src/Data/Skills/sup_int.lua": "2ba5304f1e97820b84dcf62c007a8f98c6011a6d8d59140009379a15aa02ad50",
  "src/Data/Skills/sup_str.lua": "02f01358216789d1c415d3dc94da6c9cb11d635995b0954d9d5829222840fda6",
  "src/Data/Spectres.lua": "a282bad820a7a651d1a5bce145a55f4e2c6ef843f3c0408cd60d4bc5ffa7b911",
  "src/Data/StatDescriptions/Specific_Skill_Stat_Descriptions/triggered_fractured_self.lua": "dc8c8a8be9c26e5536dc54749707b68e7133c54e3d079c848836c2d75db93869",
  "src/Data/StatDescriptions/Specific_Skill_Stat_Descriptions/triggered_mana_flare.lua": "37edd90ad727c3c380799cab2b7c671888e87afe28b75c29b1d2170ee9d984d4",
  "src/Data/StatDescriptions/gem_stat_descriptions.lua": "5ceb429bd5e5eb206bf379949a15f479b9bd38ff291cae9ca280ac6c6e239e8e",
  "src/Data/StatDescriptions/skill_stat_descriptions.lua": "e0f67449bb0b445e393bef84f0cd3030500e373eb197d6f23c4e9e65bab400d6",
  "src/Data/StatDescriptions/stat_descriptions.lua": "51ca4503c1c4b1b8b8bde2f75b68a859f33c7663b9ccdbb89d2b77db5589af6c",
  "src/Data/TimelessJewelData/LegionPassives.lua": "1a6846fee9e041374fe90494c491765ee7a6c5927efbe698e2563e9414b666bd",
  "src/Data/TradeSiteStats.lua": "aaa6a77e28138a6df6e4747d394c28675499656e41eef023f2db42f483100172",
  "src/Data/WorldAreas.lua": "694049e29b1e19f48edaa97bf8fb0c099d6a99e617a3fdfbd9f855951761f7d2",
  "src/TreeData/0_5/tree.json": "5cf88fcc5d7cac22fd35a591f0b7ae0f98841c101adf38318b62e6560d3d7dca",
  "src/TreeData/0_5/tree.lua": "5c23eab9756beeae39da9d09eed1f1f2fe49a060e392cf1794cb8b36ed713458"
}


def install_data(destination):
    def fetch(entry):
        path, digest = entry
        url = f'https://raw.githubusercontent.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/{DATA_COMMIT}/{path}'
        # Bounded retries only during installation; workers remain offline.
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=30) as response:
                    data = response.read(32 * 1024 * 1024 + 1)
                break
            except OSError:
                if attempt == 2:
                    raise
        if hashlib.sha256(data).hexdigest() != digest:
            raise SystemExit('upstream_data_digest_mismatch')
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(fetch, DATA_FILES.items()))


def patch_importer(destination):
    # Narrow backport of PR2507: preserve the new desecrated flag without
    # removing legacy fractured/crafted/mutated arrays still sent by sources.
    target = destination / 'src/Classes/ImportTab.lua'
    source = target.read_text()
    old = 'mutated = flags.mutated })'
    new = 'mutated = flags.mutated, desecrated = flags.desecrated })'
    if source.count(old) != 1:
        raise SystemExit('upstream_importer_patch_mismatch')
    target.write_text(source.replace(old, new))


def patch_deflection(destination):
    # Forgotten Warden's 0.5 modifier uses the same floored PerStat mechanism
    # as other "per N" modifiers. Keep these small source changes anchored to
    # the immutable source; never silently apply against a different version.
    target = destination / 'src/Modules/ModParser.lua'
    source = target.read_text()
    anchor = '\t["per (%d+) devotion"] ='
    extra = '\t["per (%d+) missing energy shield"] = function(num) return { tag = { type = "PerStat", stat = "MissingEnergyShield", div = num } } end,\n'
    if source.count(anchor) != 1 or extra in source:
        raise SystemExit('upstream_deflection_parser_patch_mismatch')
    target.write_text(source.replace(anchor, extra + anchor))
    target = destination / 'src/Modules/CalcDefence.lua'
    source = target.read_text()
    anchor = '\t\toutput.Armour = m_max(round(output.Armour), 0)'
    extra = '''\t\t-- Current ES is a player configuration, never inherited by a minion.
\t\t-- Read the actual input so an explicit zero is not replaced by a default.
\t\tlocal currentEnergyShieldPercent = actor == env.player and tonumber(env.configInput.multiplierCurrentEnergyShield) or 100
\t\tcurrentEnergyShieldPercent = m_min(m_max(currentEnergyShieldPercent or 100, 0), 100)
\t\toutput.MissingEnergyShield = m_max(0, output.EnergyShield * (1 - currentEnergyShieldPercent / 100))

'''
    old = '\t\toutput.DeflectionRating = modDB:Sum("BASE", nil, "DeflectionRating") + (output.Evasion * modDB:Sum("BASE", nil, "EvasionGainAsDeflection") / 100 + output.Armour * modDB:Sum("BASE", nil, "ArmourGainAsDeflection") / 100) * calcLib.mod(modDB, nil, "DeflectionRating")'
    new = old.replace('= modDB:Sum', '= (modDB:Sum').replace(' + (output.Evasion', ' + output.Evasion')
    if source.count(anchor) != 1 or source.count(old) != 1 or extra in source:
        raise SystemExit('upstream_deflection_calculation_patch_mismatch')
    target.write_text(source.replace(anchor, extra + anchor).replace(old, new))


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
        install_data(args.destination)
        patch_importer(args.destination)
        patch_deflection(args.destination)
        from patch_stonefist import patch_stonefist
        from patch_companions import patch_companions
        from patch_skill_coverage import patch_skill_coverage
        from patch_weapon_context import patch_weapon_context
        from patch_spirit_vessel import patch_spirit_vessel
        from patch_granted_skills import patch_granted_skills
        patch_weapon_context(args.destination)
        patch_stonefist(args.destination)
        patch_companions(args.destination)
        patch_spirit_vessel(args.destination)
        patch_skill_coverage(args.destination)
        patch_granted_skills(args.destination)
        from patch_martial_mechanics import patch_martial_mechanics
        from patch_damage_rules import patch_damage_rules
        from patch_upstream_fixes import patch_upstream_fixes
        patch_martial_mechanics(args.destination)
        patch_damage_rules(args.destination)
        from patch_leech_distribution import patch_leech_distribution
        patch_leech_distribution(args.destination)
        patch_upstream_fixes(args.destination)
        from patch_hit_buffs import patch_hit_buffs
        from patch_curse_mechanics import patch_curse_mechanics
        patch_hit_buffs(args.destination)
        patch_curse_mechanics(args.destination)
        from patch_beast_auras import patch_beast_auras
        patch_beast_auras(args.destination)
        (args.destination/'COMPANION_COMMIT').write_text(COMMIT+'\n')
        (args.destination/'COMPANION_DATA_COMMIT').write_text(DATA_COMMIT+'\n')
        (args.destination/'COMPANION_COMPATIBILITY').write_text(COMPATIBILITY+'\n')
    print('pinned_engine_installed')

if __name__=='__main__':main()
