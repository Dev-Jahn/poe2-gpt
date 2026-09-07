# POE2 GPT

[English](README.md) · [한국어](README.ko.md) · [Deutsch](README.de.md) · [Русский](README.ru.md) · [Português (Brasil)](README.pt-BR.md)

**Path of Exile 2**의 화폐 시세, 공식 거래소 장비 검색, 비공개 Path of Building 계산과 예산에 맞는 장비 업그레이드를 제공하는 자체 호스팅 ChatGPT 플러그인·MCP 서버입니다.

**상태: 0.4.0, 실험적 버전.** 최대 21개의 읽기 전용 MCP 도구를 구현했습니다. Homelab 배포·인증·본인 캐릭터 검증은 설치 후 진행해야 합니다. 이 저장소는 운영 중인 공용 서버나 ChatGPT 공개 디렉터리 등록을 제공하지 않습니다.

## 기능

| 영역 | 현재 제공 기능 |
|---|---|
| 화폐 시세 | Scout JSON API, 17개 카테고리 계열, 리그 선택, 검색, 묶음 견적, 캐시와 출처·조회 시각 |
| 장비 검색 | 공식 거래 사이트의 실험적 `trade2` 웹 API를 통한 타입 기반 필터와 stat 검색 |
| 저장 빌드 | 대화 밖 파일 import, 불투명 build ID, 제한된 요약과 패시브 노드 페이지 |
| PoB 계산 | 버전 고정 PoE2 PoB 엔진을 비공개 워커에서 실행; 장비 비교와 착용 조건 검증 |
| 업그레이드 | 예산과 최소 스탯 제약 안에서 명시한 캐릭터 수치 최대화 또는 비용 최소화 |

기본 리그는 **Forbidden Rites**, 기본 가격 단위는 **아이템 1개당 Exalted Orb**입니다. 다른 시즌은 `list_leagues`로 확인하세요. 영문 아이템 이름과 주요 오브의 한국어 별칭을 지원합니다. 서버 자체에는 OpenAI API 키가 필요하지 않습니다.

**PoB 코드와 XML 원문은 MCP와 모델 context에 전달하지 않습니다.** Import/export는 운영자가 직접 실행하며, 워커만 비공개 파일을 읽습니다. ChatGPT에는 ID·검증된 수치·상태만 반환합니다. PoB 코드를 채팅에 붙여 넣지 마세요. [원문 경계](docs/pob-boundary.md).

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

로컬 주소는 `http://127.0.0.1:8000/mcp`입니다. 계정에 제한된 Secure MCP Tunnel 또는 호환되는 인증을 갖춘 HTTPS 주소로 ChatGPT 웹·데스크톱에 연결하세요. 서버 자체에는 OAuth·다중 사용자 격리가 없습니다. [설치](docs/installation.md) · [배포](docs/deployment.md).

로컬 플러그인 호스트용 `.codex-plugin/plugin.json`, `.mcp.json`, Git 기반 marketplace 목록을 포함합니다. 로컬 STDIO 설치만으로 웹에 연결되지는 않습니다. 공개 ChatGPT 디렉터리 등록은 별도 심사가 필요합니다. [공식 규격](https://developers.openai.com/plugins/build/plugins).

## 사용 예

- “Forbidden Rites 디바인 시세를 엑잘 기준으로 알려줘. 조회 시각과 출처도 표시해줘.”
- “생명력 100 이상, 100 엑잘 이하인 희귀 투구를 찾아줘.”
- “Import한 build ID와 방금 검색한 매물로 20딥 안에서 생명력을 최대화해줘. 냉기 저항은 75 이상 유지해.”

마지막 요청에는 비공개 PoB 워커가 필요합니다. [도구 목록](docs/tools.md)에서 활성화 조건을 확인하세요.

## 범위와 한계

Scout는 집계 시세이며 조회 시각은 원래 가격 관측 시각이 아닙니다. 매물은 구매 전에 팔릴 수 있습니다. 거래소 웹 API는 GGG의 문서화된 OAuth 개발자 API와 다르며 변경·접근 거부가 가능합니다. 요청 제한을 존중하고 인증·challenge 응답에서 중단합니다.

PoB는 저장된 활성 설정을 계산하며 실시간 캐릭터를 조회하지 않습니다. 지원하는 착용 검사를 통과한 조합만 추천하고 불명확한 메커니즘은 `indeterminate`로 남깁니다. 최적화 범위는 보관한 후보입니다. 별도 아이템 스탯 최적화는 PoB나 캐릭터 DPS 계산이 아닙니다.

캐릭터 이름 조회, poe.ninja import, 자동 구매, 수정된 PoB export는 아직 없습니다. Docker 실행과 본인 PoB 호환성은 실제 서버에서 검증해야 합니다.

## 개발과 라이선스

```bash
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_release.py
```

실제 엔진 테스트는 별도 런타임이 없으면 skip됩니다. [기여](CONTRIBUTING.md) · [구조](docs/architecture.md) · [엔진](docs/pob-engine.md) · [CI/CD](docs/releases.md) · [보안](SECURITY.md) · [데이터 처리](docs/privacy.md).

[MIT License](LICENSE)를 적용하며 외부 구성요소는 [NOTICE](NOTICE)를 참고하세요. 영어 문서가 기준입니다. README 5개 언어는 공개 언어별 커뮤니티 지표와 한국어 포함 요청을 반영했으며 국가별 플레이어 순위라는 뜻은 아닙니다. [번역 정책](docs/localization.md).
