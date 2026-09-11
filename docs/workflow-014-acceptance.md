# 0.14 workflow acceptance ledger

Scope: all 25 handoff tickets; hideout execution remains deferred. No private input or user history is included here.

Status labels distinguish implementation, contract tests, real-engine tests, host replay, and user observation. An unchecked gate prevents release.

| Ticket | Priority | Requirement | Acceptance cases | Status |
|---|---|---|---|---|
| MCP-001 | P0 | 호스트에서 실제 사용 가능한 기능·스키마를 자기 기술 | MCP-001-T01, MCP-001-T02, MCP-001-T03 | Partial: runtime inventory and schema pages; final host replay pending |
| MCP-002 | P0 | 정적 inspection을 계산 엔진 실패에서 분리하고 한 번에 요약 | MCP-002-T01, MCP-002-T02, MCP-002-T03 | Partial: native calculation-free loader/cache verified; complete profile/fallback acceptance pending |
| MCP-003 | P0 | 주력 스킬·행위자·계산 문맥을 명시적으로 선택 | MCP-003-T01, MCP-003-T02, MCP-003-T03 | Partial: player/minion instance targeting verified; copy/component coverage pending |
| MCP-004 | P0 | 원본 보존형 젬·패시브·장비 공동 changeset 평가 | MCP-004-T01, MCP-004-T02, MCP-004-T03 | Partial: immutable typed edits; transition solver and full edit acceptance pending |
| MCP-005 | P0 | 검증 범위를 분리하고 조건부 추천을 구조화 | MCP-005-T01, MCP-005-T02, MCP-005-T03 | Partial: scoped metric explanations; sensitivity/frontier pending |
| MCP-006 | P0 | 스냅샷·사용자 변경·추천 실행 상태의 revision 관리 | MCP-006-T01, MCP-006-T02, MCP-006-T03 | Partial: revision-locked decision lifecycle; encrypted observations, conflicts and source distinction verified; source reconciliation pending |
| MCP-007 | P0 | 게임 조건/보조 호환/자원 공급원 linter | MCP-007-T01, MCP-007-T02, MCP-007-T03, MCP-007-T04 | Partial: typed condition/event linter; automatic full-build facts and independent game-rule oracles pending |
| MCP-008 | P0 | 의식·지속 피격에서 실제 회복 가능성을 평가 | MCP-008-T01, MCP-008-T02, MCP-008-T03, MCP-008-T04 | Partial: deficit/event integrator verified; native parameter binding and acceptance replay pending |
| MCP-009 | P1 | 전체 패시브 그래프와 사람용 경로 계획 | MCP-009-T01, MCP-009-T02, MCP-009-T03, MCP-009-T04 | Partial: complete native graph and route search verified; jewel/weapon point constraints pending |
| MCP-010 | P1 | 새 소켓과 보조젬 포트폴리오 비교 | MCP-010-T01, MCP-010-T02, MCP-010-T03 | Partial: native gem catalog and joint support portfolio verified in one worker; full socket/BOM and condition acceptance pending |
| MCP-011 | P1 | 원본→변환 장비 비교와 미확정 롤 처리 | MCP-011-T01, MCP-011-T02, MCP-011-T03 | Pending |
| MCP-012 | P1 | 요구치·재장착·전환 순서 통합 solver | MCP-012-T01, MCP-012-T02, MCP-012-T03 | Partial: native requirement sources and owned bridge order verified; mixed edit transitions and correction BOM pending |
| MCP-013 | P1 | 시장 검색·환율·rate-limit을 하나의 계획으로 조율 | MCP-013-T01, MCP-013-T02, MCP-013-T03, MCP-013-T04 | Pending |
| MCP-014 | P1 | 검증 가능한 장비·젬·패시브 통합 구매안 | MCP-014-T01, MCP-014-T02, MCP-014-T03 | Pending |
| MCP-015 | P1 | 영속 evidence receipts·보고서·산출물 일관성 | MCP-015-T01, MCP-015-T02, MCP-015-T03 | Partial: opt-in encrypted decisions and shared artifact digest; complete artifact acceptance pending |
| MCP-016 | P1 | 한국어 명칭·랜드마크·typed entity navigation | MCP-016-T01, MCP-016-T02, MCP-016-T03 | Partial: typed catalog, verified Korean fallback and route landmarks; final navigation replay pending |
| MCP-017 | P1 | 한 경로·단계별 실행·원복 중심 계획 UX | MCP-017-T01, MCP-017-T02, MCP-017-T03 | Partial: plan steps and lifecycle; actionable consolidated route/rollback pending |
| MCP-018 | P1 | 작업 단위 관측·성능예산·오류 복구 | MCP-018-T01, MCP-018-T02, MCP-018-T03 | Pending |
| MCP-019 | P1 | 가이드의 variant·단계·전제조건 추출 | MCP-019-T01, MCP-019-T02, MCP-019-T03 | Pending |
| MCP-020 | P2 | 계정·로그인·거래소 이동 handoff 가시성 | MCP-020-T01, MCP-020-T02, MCP-020-T03 | Partial: UI setup action and deferred travel distinction; complete account capability tests pending |
| MCP-021 | P2 | 지도·의식·서판 조건별 위험/수익 보조 | MCP-021-T01, MCP-021-T02, MCP-021-T03 | Pending |
| MCP-022 | P2 | 레벨업·전직·해금 milestone planner | MCP-022-T01, MCP-022-T02, MCP-022-T03 | Partial: observation-backed milestones, unknown unlocks and separate point pools; complete native/effective/socket acceptance pending |
| MCP-023 | P2 | 판매·제작·콘텐츠 선택의 가치 평가 | MCP-023-T01, MCP-023-T02, MCP-023-T03 | Pending |
| MCP-024 | P2 | 커런시 보유·투자·환전 계획 | MCP-024-T01, MCP-024-T02, MCP-024-T03 | Pending |
| MCP-025 | P1 | 호스트 실제 사용 회귀 평가와 독립 oracle | MCP-025-T01, MCP-025-T02, MCP-025-T03 | Partial: initial unit/native/MCP regressions; complete 79-case mapping and host replay pending |

## Release gates

- [ ] Every acceptance case mapped to executable tests or explicit external evidence.
- [ ] No missing private fixture represented as a successful replay.
- [ ] Independent real-engine differential checks, both supported architectures.
- [ ] Actual MCP schema/owner isolation/empty-value contracts.
- [ ] Complete final tree CI before merge and deployment.
- [ ] Production and external MCP verification after deployment.
