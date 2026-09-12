# POE2 GPT

[English](README.md) · [한국어](README.ko.md) · [Deutsch](README.de.md) · [Русский](README.ru.md) · [Português (Brasil)](README.pt-BR.md)

**Path of Exile 2**의 화폐 시세, 공식 거래소 장비 검색, 비공개 Path of Building 계산과 예산에 맞는 장비 업그레이드를 제공하는 자체 호스팅 ChatGPT 플러그인·MCP 서버입니다.

**상태: 0.14.1, 실험적 버전.** 최대 100개의 MCP 도구를 구현했습니다. Homelab 배포·인증·본인 캐릭터 검증은 설치 후 진행해야 합니다. 이 저장소는 운영 중인 공용 서버나 ChatGPT 공개 디렉터리 등록을 제공하지 않습니다.


0.14는 원본 보존형 빌드 실험, 스킬·행위자 지정, 전체 패시브 경로·보조 비교, 통합 구매 근거, 회복 분석과 사용자 인증이 필요한 실행표 다운로드를 추가합니다. [작업 흐름과 제한](docs/workflows.md)을 참고하세요. 은신처 이동은 향후 기능으로 남깁니다.
## 기능

0.12에서는 빈 조회 응답, 단일 요청 슬롯 조회, 비용 0의 장비 해제 추천, 후보별 매물·탈락 이유·환율 진단을 보완했습니다. 매물 검색 기본값은 즉시구매(`securable`)입니다. 반환 링크는 공식 검색 페이지를 열며, ChatGPT 클릭만으로 게임 내 은신처 이동은 아직 지원하지 않습니다. [상세 범위](docs/review-012.md).

0.11에서는 장착·저장 장비의 옵션, 스킬·보조젬, 저장·적용 설정을 조회하고
전체 진단을 페이지로 회수할 수 있습니다. Ninja의 요청 시점 조회 여부를
표시하며, 목적별 계산 검증·최소 비용 착용 복구·매물 상세 조회를 추가했습니다.
[리뷰 지적사항 대응과 검증 시나리오](docs/review-followup.md).

| 영역 | 현재 제공 기능 |
|---|---|
| 화폐 시세 | Scout JSON API, 17개 카테고리 계열, 리그 선택, 검색, 묶음 견적, 캐시와 출처·조회 시각 |
| 장비 검색 | 공식 거래 사이트의 실험적 `trade2` 웹 API를 통한 타입 기반 필터와 stat 검색 |
| 저장 빌드 | 계정 태그+캐릭터명 자동 조회 또는 ChatGPT .txt 첨부, 불투명 build ID, 제한된 요약과 패시브 노드 페이지 |
| PoB 계산 | 버전 고정 PoE2 PoB 엔진을 비공개 워커에서 실행; 장비 비교와 착용 조건 검증 |
| 업그레이드 | 예산과 최소 스탯 제약 안에서 명시한 캐릭터 수치 최대화 또는 비용 최소화 |

기본 리그는 **Forbidden Rites**, 기본 가격 단위는 **아이템 1개당 Exalted Orb**입니다. 다른 시즌은 `list_leagues`로 확인하세요. PoE2DB에서 대조한 영문·한국어 명칭 DB를 포함합니다. 화폐·장비 베이스·직업·선택 스킬에 확인된 한국어 이름을 표시하고, `search_game_terms`로 명칭과 출처를 조회할 수 있습니다. 번역이 없는 항목은 영문을 유지합니다. 서버 자체에는 OpenAI API 키가 필요하지 않습니다.

엔진은 고정된 PoB2 개발 소스와 해시를 검증한 0.5.5 데이터 패치를 사용합니다. 0.10에서는 Spirit Vessel 복제 공격, 포획한 야수의 옵션, 무술가 메커니즘, PoE2 흡수·꿰뚫기 규칙, 충전 및 Mountain’s Teachings 전투 시나리오를 추가했습니다. 명시적인 [계산 가정](docs/calculation-assumptions.md)은 현재 빌드와 장비 후보에 동일하게 적용하며, 실제 전투에서 관측한 상태로 취급하지 않습니다. [최신 리그 지원 범위](docs/league-coverage.md)와 [업스트림 검토 기록](docs/upstream-review-010.md)에서 검증된 계산과 남은 제한을 확인할 수 있습니다. 개별 계산 범위와 누락 입력은 `mechanics`에 표시합니다. 선택 스킬과 플레이어·선택 소환수 DPS를 구분하며, FullDPS는 설정된 경우에만 제공합니다. 미확인 패시브·미해석 효과·지원하지 않는 설정은 결과에 표시하고 검증된 업그레이드 추천에서 제외합니다. [엔진 호환 범위](docs/pob-engine.md) · [한국어 명칭 수록 범위](docs/localization.md).

아이템·패시브가 부여하는 스킬의 레벨도 현재 캐릭터 레벨과 능력치에 맞춰 다시 계산합니다. 세부 지원 범위와 남은 제약은 [최신 리그 계산 지원표](docs/league-coverage.md)에서 확인할 수 있습니다.

**MCP는 PoB 코드와 XML 원문을 반환하지 않습니다.** 비공개 가져오기 서비스와 PoB 워커가 원본을 처리하며, ChatGPT에는 제한된 요약·ID·검증된 수치·상태를 반환합니다. 서버로 파일을 직접 복사하거나 터미널 import 명령을 실행할 필요가 없습니다. PoB 코드를 채팅에 붙여 넣지 마세요. ChatGPT 자체의 첨부파일 처리는 플러그인이 제어할 수 없습니다. [원문 경계](docs/pob-boundary.md).

0.9.0부터 MCP 초기화 응답, 상태 조회 도구의 `server_version`, `/healthz`에 실제 프로젝트 버전을 표시합니다. ChatGPT가 별도로 관리하는 플러그인 버전은 서버에서 직접 수정할 수 없습니다. 연결을 Refresh한 뒤에도 화면에 `1.0.0`이 남으면 `get_pob_engine_status`로 실제 배포 버전을 확인하세요. [버전 표시와 업데이트](docs/installation.md#version-labels).

## 설치

Python 3.11 이상이 필요합니다. PoB 워커에는 Linux와 고정된 Lua 런타임이 필요합니다.

```bash
git clone https://github.com/Dev-Jahn/poe2-gpt.git
cd poe2-gpt
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m poe2_companion.check
```

Windows에서는 `py -3 -m venv .venv`로 환경을 만들고 Python 명령에 `.venv\Scripts\python.exe`를 사용하세요. 기존 `poe2_companion` 모듈과 `poe2-companion` 명령도 유지합니다.

Homelab MCP 실행:

```bash
docker compose up -d --build
```

로컬 주소는 `http://127.0.0.1:8000/mcp`입니다. 계정에 제한된 Secure MCP Tunnel 또는 호환되는 인증을 갖춘 HTTPS 주소로 ChatGPT 웹·데스크톱에 연결하세요. Cloudflare가 OAuth를 제공하며, 각 MCP 인스턴스는 지정된 사용자 한 명만 허용합니다. [설치](docs/installation.md) · [배포](docs/deployment.md).

인바운드가 차단된 Mac mini에서는 [Mac mini + Cloudflare 설치 안내](docs/mac-mini-cloudflare.md)를 따르세요. ARM64/amd64 Linux 컨테이너, Managed OAuth와 서버 JWT 검증, 로그인 후 자동 실행을 지원합니다.

[친구 두 명과 서버 공유](docs/friends.md): 같은 Mac에서 사용자별 MCP 인증·빌드 저장소·거래 검색 상태·PoB 워커를 분리합니다. 도메인·터널·공개 시세 캐시는 공유합니다.

로컬 플러그인 호스트용 `.codex-plugin/plugin.json`, `.mcp.json`, Git 기반 marketplace 목록을 포함합니다. 로컬 STDIO 설치만으로 웹에 연결되지는 않습니다. 공개 ChatGPT 디렉터리 등록은 별도 심사가 필요합니다. [공식 규격](https://developers.openai.com/plugins/build/plugins).

## 캐릭터 연결

다음 두 가지 방식만 사용합니다.

1. **PoE2 계정 태그 + 캐릭터명:** “내 계정은 `Example#1234`, 캐릭터는 `캐릭터이름`이야. 조회해줘.” MCP가 poe.ninja에서 리그를 확인하고 PoB를 서버 내부에서 자동으로 가져옵니다. 리그가 모호한 경우에만 선택합니다.
2. **ChatGPT에 `.txt` 파일 첨부:** PoB 내보내기 코드가 들어 있는 UTF-8 텍스트 파일을 첨부하고 “이 빌드를 가져와줘”라고 요청합니다. ChatGPT가 파일 참조를 MCP에 전달하고 서비스가 원본 바이트를 직접 내려받습니다. 코드 평문 입력이나 모델의 코드 재작성은 사용하지 않습니다.

MCP가 반환한 빌드 ID는 같은 대화에서 재계산·착용 조건 검증·장비 업그레이드 추천에 이어서 사용합니다. 서버의 물리적 위치로 파일을 전송하는 경로와 `import-build` CLI는 제거했습니다. PoB 원문을 읽거나 반복하지 않도록 도구를 구성했지만, ChatGPT 자체의 첨부파일 처리·보관은 플러그인이 제어할 수 없습니다.

### poe.ninja 사전 연결

GGG 또는 Steam 퍼블리싱 계정은 [poe.ninja 계정](https://poe.ninja/account)에서 **Connect**를 누르고 GGG에서 **Authorize**로 승인합니다.

**카카오 계정은 먼저 다음 절차를 진행하세요.**

1. 카카오 로그인 상태에서 [카카오 POE 계정 관리](https://poe.kakaogames.com/my-account/connections)로 이동합니다.
2. 상단 **English**를 클릭합니다. `/login/transfer`를 통해 GGG로 로그인 상태를 전달합니다.
3. [poe.ninja 계정](https://poe.ninja/account)에서 **Connect**를 클릭합니다.
4. GGG의 **Authorize**로 연동을 승인합니다.

Ninja에서 조회 가능한 공개 프로필이어야 합니다. 이 절차는 사용자가 확인한 카카오 연결 경로이며, 공급자 UI 변경 시 달라질 수 있습니다.

“캐릭터 갱신해줘”는 Ninja의 **Refresh character** 요청을 보냅니다. 브라우저의 Ninja 로그인과 MCP 인증은 별개이므로, 능동 갱신에는 운영자가 사용자별 Ninja 세션을 별도로 설정해야 합니다. 없거나 만료되면 `authentication_required`를 반환하며, 이미 공개된 캐릭터 조회는 계속 사용할 수 있습니다. 대기시간을 지키며 자동 재시도하지 않습니다. 자세한 운영 방식은 [캐릭터 연동](docs/characters.md)을 참고하세요.

## 사용 예

- “Forbidden Rites 디바인 시세를 엑잘 기준으로 알려줘. 조회 시각과 출처도 표시해줘.”
- “생명력 100 이상, 100 엑잘 이하인 희귀 투구를 찾아줘.”
- “Import한 build ID와 방금 검색한 매물로 20딥 안에서 생명력을 최대화해줘. 냉기 저항은 75 이상 유지해.”

마지막 요청에는 비공개 PoB 워커가 필요합니다. [도구 목록](docs/tools.md)에서 활성화 조건을 확인하세요.

## 업데이트 후 새 기능이 보이지 않을 때

MCP 연결을 매번 삭제·재등록할 필요는 없습니다. **ChatGPT의 Plugins에서 POE2 연결을 열고 Refresh를 누른 뒤 새 대화**를 시작하세요. `get_character`가 표시되고 활성화되어 있으면 계정 태그+캐릭터명으로 빌드를 가져올 수 있습니다. 새 대화만 시작하면 이전 도구 목록이 남아 있을 수 있습니다. [OpenAI 공식 갱신 절차](https://developers.openai.com/plugins/deploy/connect-chatgpt).

시세·게임 데이터·계산 로직만 바뀌고 도구 정의가 동일하면 서버 재배포로 반영됩니다. 도구 추가나 입출력 형식 변경이 있을 때는 연결의 Refresh가 필요합니다. 각자 별도로 만든 guest 연결도 확인하세요. [업데이트와 진단](docs/installation.md#updating-an-existing-chatgpt-connection).

## 범위와 한계

Scout는 집계 시세이며 조회 시각은 원래 가격 관측 시각이 아닙니다. 매물은 구매 전에 팔릴 수 있습니다. 거래소 웹 API는 GGG의 문서화된 OAuth 개발자 API와 다르며 변경·접근 거부가 가능합니다. 요청 제한을 존중하고 인증·challenge 응답에서 중단합니다.

PoB는 저장된 활성 설정을 계산하며 실시간 캐릭터를 조회하지 않습니다. 지원하는 착용 검사를 통과한 조합만 추천하고 불명확한 메커니즘은 `indeterminate`로 남깁니다. 최적화 범위는 보관한 후보입니다. 별도 아이템 스탯 최적화는 PoB나 캐릭터 DPS 계산이 아닙니다.

계정 태그와 캐릭터명으로 poe.ninja 스냅샷을 가져올 수 있습니다. 자동 구매와 수정된 PoB export는 제공하지 않습니다. Docker 실행과 본인 PoB 호환성은 실제 서버에서 검증해야 합니다.

## 개발과 라이선스

```bash
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_release.py
```

실제 엔진 테스트는 별도 런타임이 없으면 skip됩니다. [기여](CONTRIBUTING.md) · [구조](docs/architecture.md) · [엔진](docs/pob-engine.md) · [CI/CD](docs/releases.md) · [보안](SECURITY.md) · [데이터 처리](docs/privacy.md).

[MIT License](LICENSE)를 적용하며 외부 구성요소는 [NOTICE](NOTICE)를 참고하세요. 영어 문서가 기준입니다. README 5개 언어는 공개 언어별 커뮤니티 지표와 한국어 포함 요청을 반영했으며 국가별 플레이어 순위라는 뜻은 아닙니다. [번역 정책](docs/localization.md).
