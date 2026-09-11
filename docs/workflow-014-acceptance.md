# 0.14 workflow acceptance ledger

Scope: all 25 handoff tickets; hideout execution remains deferred. No private input or user history is included here.

Status labels distinguish implementation, contract tests, real-engine tests, host replay, and user observation. An unchecked gate prevents release.

| Ticket | Priority | Requirement | Acceptance cases | Status |
|---|---|---|---|---|
| MCP-001 | P0 | 호스트에서 실제 사용 가능한 기능·스키마를 자기 기술 | MCP-001-T01, MCP-001-T02, MCP-001-T03 | Implemented; executable cases mapped; final tree/release checks pending |
| MCP-002 | P0 | 정적 inspection을 계산 엔진 실패에서 분리하고 한 번에 요약 | MCP-002-T01, MCP-002-T02, MCP-002-T03 | Implemented; executable cases mapped; final tree/release checks pending |
| MCP-003 | P0 | 주력 스킬·행위자·계산 문맥을 명시적으로 선택 | MCP-003-T01, MCP-003-T02, MCP-003-T03 | Implemented; executable cases mapped; final tree/release checks pending |
| MCP-004 | P0 | 원본 보존형 젬·패시브·장비 공동 changeset 평가 | MCP-004-T01, MCP-004-T02, MCP-004-T03 | Implemented; executable cases mapped; final tree/release checks pending |
| MCP-005 | P0 | 검증 범위를 분리하고 조건부 추천을 구조화 | MCP-005-T01, MCP-005-T02, MCP-005-T03 | Implemented; executable cases mapped; final tree/release checks pending |
| MCP-006 | P0 | 스냅샷·사용자 변경·추천 실행 상태의 revision 관리 | MCP-006-T01, MCP-006-T02, MCP-006-T03 | Implemented; executable cases mapped; final tree/release checks pending |
| MCP-007 | P0 | 게임 조건/보조 호환/자원 공급원 linter | MCP-007-T01, MCP-007-T02, MCP-007-T03, MCP-007-T04 | Implemented; executable cases mapped; final tree/release checks pending |
| MCP-008 | P0 | 의식·지속 피격에서 실제 회복 가능성을 평가 | MCP-008-T01, MCP-008-T02, MCP-008-T03, MCP-008-T04 | Implemented; executable cases mapped; final tree/release checks pending |
| MCP-009 | P1 | 전체 패시브 그래프와 사람용 경로 계획 | MCP-009-T01, MCP-009-T02, MCP-009-T03, MCP-009-T04 | Implemented; executable cases mapped; final tree/release checks pending |
| MCP-010 | P1 | 새 소켓과 보조젬 포트폴리오 비교 | MCP-010-T01, MCP-010-T02, MCP-010-T03 | Implemented; executable cases mapped; final tree/release checks pending |
| MCP-011 | P1 | 원본→변환 장비 비교와 미확정 롤 처리 | MCP-011-T01, MCP-011-T02, MCP-011-T03 | Implemented; executable cases mapped; final tree/release checks pending |
| MCP-012 | P1 | 요구치·재장착·전환 순서 통합 solver | MCP-012-T01, MCP-012-T02, MCP-012-T03 | Implemented; executable cases mapped; final tree/release checks pending |
| MCP-013 | P1 | 시장 검색·환율·rate-limit을 하나의 계획으로 조율 | MCP-013-T01, MCP-013-T02, MCP-013-T03, MCP-013-T04 | Implemented; executable cases mapped; final tree/release checks pending |
| MCP-014 | P1 | 검증 가능한 장비·젬·패시브 통합 구매안 | MCP-014-T01, MCP-014-T02, MCP-014-T03 | Implemented; executable cases mapped; final tree/release checks pending |
| MCP-015 | P1 | 영속 evidence receipts·보고서·산출물 일관성 | MCP-015-T01, MCP-015-T02, MCP-015-T03 | Implemented; executable cases mapped; final tree/release checks pending |
| MCP-016 | P1 | 한국어 명칭·랜드마크·typed entity navigation | MCP-016-T01, MCP-016-T02, MCP-016-T03 | Implemented; executable cases mapped; final tree/release checks pending |
| MCP-017 | P1 | 한 경로·단계별 실행·원복 중심 계획 UX | MCP-017-T01, MCP-017-T02, MCP-017-T03 | Implemented; executable cases mapped; final tree/release checks pending |
| MCP-018 | P1 | 작업 단위 관측·성능예산·오류 복구 | MCP-018-T01, MCP-018-T02, MCP-018-T03 | Implemented; executable cases mapped; final tree/release checks pending |
| MCP-019 | P1 | 가이드의 variant·단계·전제조건 추출 | MCP-019-T01, MCP-019-T02, MCP-019-T03 | Implemented; executable cases mapped; final tree/release checks pending |
| MCP-020 | P2 | 계정·로그인·거래소 이동 handoff 가시성 | MCP-020-T01, MCP-020-T02, MCP-020-T03 | Implemented; executable cases mapped; final tree/release checks pending |
| MCP-021 | P2 | 지도·의식·서판 조건별 위험/수익 보조 | MCP-021-T01, MCP-021-T02, MCP-021-T03 | Implemented; executable cases mapped; final tree/release checks pending |
| MCP-022 | P2 | 레벨업·전직·해금 milestone planner | MCP-022-T01, MCP-022-T02, MCP-022-T03 | Implemented; executable cases mapped; final tree/release checks pending |
| MCP-023 | P2 | 판매·제작·콘텐츠 선택의 가치 평가 | MCP-023-T01, MCP-023-T02, MCP-023-T03 | Implemented; executable cases mapped; final tree/release checks pending |
| MCP-024 | P2 | 커런시 보유·투자·환전 계획 | MCP-024-T01, MCP-024-T02, MCP-024-T03 | Implemented; executable cases mapped; final tree/release checks pending |
| MCP-025 | P1 | 호스트 실제 사용 회귀 평가와 독립 oracle | MCP-025-T01, MCP-025-T02, MCP-025-T03 | Implemented; executable cases mapped; final tree/release checks pending |

## Release gates

- [x] Every acceptance case mapped to executable tests or explicit external evidence; [machine-readable map](workflow-014-cases.json).
- [x] No missing private fixture represented as a successful replay.
- [ ] Independent real-engine differential checks, both supported architectures.
- [ ] Actual MCP schema/owner isolation/empty-value contracts.
- [ ] Complete final tree CI before merge and deployment.
- [ ] Production and external MCP verification after deployment.

## WIP verification checkpoints

- `177a7f6cc60326798d001d06605a74474cc1fa4e`, tree `54dab55e4250b97fab3caf921eaa4516e8a81f72`: Mini reported isolated ARM 469 passed, zero skipped, no private mounts/network. The two previous ordinary-JSON 8192-byte failures pass. This is not final release/host replay evidence.
- Currency/guide/economics/market unit contracts: 12 passed. Workflow tracing: 3 passed, including an actual in-memory MCP session with empty inspection records and output-schema validation.
- Native private timing and hot static cache while the loader is busy: 3 passed locally. CPU timing is not measured; worker execution and IPC round-trip are separate inclusive spans.
- General Python suite before the final private telemetry header changes: 274 passed, 207 skipped. Native execution is a separate gate; these skips are not counted as native passes.

## Independent rule source boundary

The public [Waystone data](https://poe2db.tw/us/Waystones), checked 2026-09-11, supports the meanings of reduced Life/ES recovery, cooldown recovery, extra critical damage and maximum resistance modifiers. Its roll ranges differ from the pinned hand-written `src/Data/ModMap.lua`; this implementation does not reuse that table as a current-game oracle. The page does not declare an exact patch revision. Responses preserve this limitation and do not certify map safety, patch coverage, reflection rules or future drop probabilities.

- `798900b592449024b89c2ff38079be7a9689c7aa`, tree `4728c7564ecc5c4e16aba65da3a1334d16363538`: Mini reported 482 passed, zero skipped, isolated ARM full suite with public synthetic fixtures only. No production deployment or historical private replay.
- Next local checkpoint: Vessel owner/source matching (three native requests), private passive click-order endpoint and mixed gem/equipment sequence each passed. Mixed sequence recalculates prefixes from the immutable original; its work budget counts attempted native edges. Python execution/rollback, audit-size and recovery contracts: 18 passed; mypy 60 modules and Ruff passed.

- `832f3ff0536058955935912cf1136424250bcba1`, tree `ff51d30dfcb4c16cd7eba36b1af9a1be3a19460e`: Mini reported isolated ARM full suite 492 passed, zero skipped (481.23s), and 52 targeted passes. Public synthetic fixtures only; no production or historical private replay.
- Next checkpoint local Python suite: 292 passed, 214 native/platform skips; Python coverage 85.89% with the existing 85% gate unchanged. New native component and full-path portfolio tests: 2 passed; explicit shared weapon point budget test: 1 passed; joint Ghost Dance/ES removal: 1 passed. All configured tool examples and disabled/busy fallback schemas are validated over an actual in-memory MCP session. Mypy checks 65 modules and now checks untyped bodies in the workflow contract modules; Ruff passed before final staging.
- Scout history conversion was checked against the public [EconomyCache implementation](https://github.com/poe2scout/poe2scout/blob/0e3f718b709dfa0c92eeeea7425b4e63a209b97c/net/Poe2scout.Api/EconomyCache.cs): historical values use the reference price from the same bucket, while current values use the current reference price. The synthetic upstream fixture now preserves that distinction.

## Release candidate verification (not production)

- Checkpoint6 `226ea7b50f6db9b086063b762ca36c482e830349`, tree `703775362f61714a6021706295c1bfda14ec261a`: Mini reported ARM **506 passed, zero skipped**, 503.02s, isolated/no network/no private host mounts. This preceded the final HTTP replay/export/discovery changes and is not final release evidence.
- New local authenticated HTTP MCP replay: four synthetic tasks passed against a real worker. Static discovery/target selection: 4 calls; two immutable change comparisons: 6; exact candidate/cost explanation: 6; execution, partial application, adverse observation and owner checks: 12. The final task includes three intentional cross-owner denials. Every tool result's output schema and ordinary JSON 8192-byte limit were checked. Wrong-subject assertions: 0/3 violations; source-state assertions: 0/5 violations; one actionable route followed by one adverse-outcome block. These are scripted contract metrics, not LLM answer accuracy or observed gameplay success.
- Local native isolated-target support differential passed: the supplied isolated scenario multiplies hit damage by the pinned 1.2 rule; ordinary packs do not inherit it. The same test verifies native gem requirements and that a purchased gem does not inherit existing upgraded sockets.
- Download tests use authenticated HTTP MCP and GET/HEAD, verify content bytes/SHA-256 and Markdown/JSON identity, reject altered rendered objects, check other-owner/unauthenticated access, and confirm deletion invalidates links. Export storage is encrypted when persistence is explicitly requested.
- Additional contracts now cover all adjacent ordinary/weapon candidates, rejection of free travel through the opposite weapon branch, cannot-attack intervals and lossless event-graph pagination. Execution labels include effect/coordinate/landmark information; missing entity labels block execution.
- The release marker is `forbidden-rites-0.5.5-v5`; the upstream engine/data commits are unchanged. Final containers must be rebuilt with this marker. Earlier v4 tests remain historical checkpoint evidence only.

## Deliberate evidence limits

The handoff requires unknown rules, missing user progress, absent roll/drop probabilities and inaccessible guide variants to remain explicit. Implementing those contracts does not certify every game mechanic or invent unavailable inputs. Historical private fixture identities were not provided in executable form, so this release's synthetic task replays are labeled separately. Actual installed-host verification and final CI must be appended before release; gameplay success remains user observation.
