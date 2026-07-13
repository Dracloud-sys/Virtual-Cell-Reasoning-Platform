# 불멸화 시계열 판단 Benchmark v1
### VCRP PR7 산출물 — passage별 raw 시계열을 규칙 기반 판단에 반영

> 목적: 단일 시점·범주형 판정이 버리던 **시간축 정보**(passage별 DT/PDL)를 구조화하여,
> 플랫폼이 사용자가 지정한 `DT_trend`에 의존하지 않고 **원자료에서 직접** trajectory를 도출하는지 고정한다.
> 위치: `tests/benchmarks/immortalization_timeseries_v1.md` + `immortalization_timeseries_v1.yaml`(하네스용).
> 범위: raw 시계열 → deterministic trajectory. 새로운 예측 모델이 아니다.

---

## 0. 핵심 불변식

1. **시계열만으로 immortalization을 확정하지 않는다.** trajectory는 증식 경과일 뿐, 종합 판단(candidate_status)이 아니다.
2. **원자료와 해석값을 분리한다.** `PassageObservation`(raw) → `TrajectoryAssessment`(derived features). trajectory는 raw를 복사하지 않는다.
3. **모든 임계값은 명시적 정책이다.** `TrajectoryThresholds`는 v1 benchmark policy이며 생물학적 보편 법칙이 아니다.
4. **기존 v0 snapshot 입력은 변경 없이 동작한다.** 시계열은 선택 사항이다.

---

## 1. trajectory 어휘 (v1 = 8단계)

| state | 의미 |
|---|---|
| `insufficient_series` | 시점 부족으로 trajectory 판단 불가 |
| `stable_growth` | PDL 증가 + DT 안정 |
| `progressive_slowdown` | PDL 증가하지만 DT 지속 악화 |
| `plateau` | PDL 증가가 사실상 정지 |
| `recovery_after_plateau` | plateau 이후 최소 2구간 지속 회복 |
| `transient_recovery` | 회복 관찰됐으나 지속성 확인 구간 부족 |
| `re_arrest` | plateau→회복→재정지 |
| `conflicting_trajectory` | PDL/DT 방향 불일치로 분류 불안정 |

> trajectory ≠ candidate_status. 예: `progressive_slowdown` + `senescence_or_stress_prone`,
> 또는 `transient_recovery` + `insufficient_evidence`. senescence marker가 없으면 회복이 있어도 후보 확정 불가.

---

## 2. 판정 우선순위 (terminal-anchored, hardening)

복합 trajectory를 단순 현재 상태로 덮어쓰지 않되, **최종(terminal) 상태를 과거 국소 패턴보다 우선**한다.

- **`re_arrest`는 series가 실제로 flat으로 끝날 때만** 생성한다. 과거에 F→G→F가 있었더라도 terminal run이
  성장(G)이면 `re_arrest`가 아니라 `recovery_after_plateau`/성장 계열로 분류한다.
- `plateau_interval`은 **terminal flat run만** 나타낸다 (중간 성장 구간을 포함하지 않는다).
- historical crisis와 current state는 `rationale`에서 구분한다.
- 최근 DT 악화가 전체 early/late median에 희석될 수 있으므로, recent window가 선행 window 대비 worsening fold
  이상이면 `terminal_dt_deterioration`으로 표시하고 report `uncertainty`에 노출한다 (status를 강제로 바꾸지는 않음).

탐지 순서(terminal run 기준):

```
terminal flat  : re_arrest (직전 plateau→recovery 존재 시) → conflicting(DT 개선) → plateau
terminal growth: recovery_after_plateau / transient_recovery (직전 plateau 존재 시)
                 → progressive_slowdown (DT worsening) → stable_growth
usable PDL < 3 : insufficient_series
```

---

## 3. 시계열 품질 검증 (오류 vs flag)

| 상황 | 처리 |
|---|---|
| 음수/0 이하 DT | 입력 오류 (모델 검증) |
| passage 중복 | 입력 오류 (모델 검증) |
| PDL 소폭 감소 | quality flag (`non_monotonic_pdl`) → **PDL override 차단** |
| usable PDL < 3 | `insufficient_series` + `insufficient_timepoints` |
| 일부 DT 누락 | 부분 계산 + `missing_dt` |
| 일부 PDL 누락 | 부분 계산 + `missing_pdl` |
| 큰 PDL passage 간격 (> `max_supported_passage_gap`) | `sparse_passage_sampling` → **PDL override 차단** |
| 정렬되지 않은 입력 | 내부 정렬(원본 불변) |

### 축별(axis-specific) gating (hardening)

품질 게이팅은 **전체 trajectory가 아니라 PDL/DT 축별로** 적용한다.

- **usable count 분리**: `usable_PDL_timepoints`, `usable_DT_timepoints`를 전체 관측 수와 별도로 센다.
  trajectory state는 usable PDL ≥ `min_timepoints`, DT trend는 usable DT ≥ `min_timepoints`일 때만 도출한다.
- **blocking vs warning**: `non_monotonic_pdl`, `sparse_passage_sampling`은 해당 축(PDL)의 snapshot override를
  **차단**(blocking)한다. `irregular_passage_intervals`, `missing_*`는 경고(warning)이며 자체로 전체 trajectory를
  폐기하지 않는다. 차단된 derived trend는 `derived_input`에 적용된 것처럼 표시하지 않고, 사유를 `blocked_overrides`
  (구조화 최상위 필드)에 노출한다.
- **sparse는 PDL 축 기준**: `sparse_passage_sampling`은 전체 관측이 아니라 **PDL을 담은 passage들 사이의 간격**으로
  판정한다. 따라서 DT가 매 passage 촘촘히 측정돼도 PDL이 드문드문(예: passage 1/15/30) 측정됐다면 sparse로 잡혀
  PDL override가 차단된다. (`irregular_passage_intervals`는 전체 관측 cadence 기준의 경고로 유지.)
- **DT 임계값 stable band**: `fold ≤ improving`(=0.75) → improved; `|fold−1| ≤ stable_relative`(=0.25) → stable;
  `fold ≥ worsening`(=1.50) → worsening; **stable band 상한(1.25)과 worsening(1.50) 사이는 `unknown`**(stable로
  반올림하지 않음). 임계값 순서는 Pydantic으로 검증한다.
- **DT unknown ≠ stable**: DT를 도출할 수 없으면 `derived_DT_trend=unknown`이며 snapshot DT를 override하지 않는다.
  PDL만 증가하고 DT가 unknown이면 state는 `stable_growth`(API 호환을 위해 이름 유지)이되, rationale은
  "PDL increases, but doubling-time stability is unverified."로 DT 안정성을 단정하지 않는다.

> `possible_outlier` / `sparse_late_passage`는 v1에서 **의도적으로 미도입**했다. 단일 spike는 early/late median
> 창이 이미 흡수하며, 전역 median/MAD outlier 규칙은 실제 terminal deterioration **추세**를 outlier로 오탐한다.
> 모든 선언된 `SeriesQualityFlag`는 실제로 생성된다.

---

## 4. 사례 (TS01–TS12)

각 사례의 `observations`·snapshot·expected는 YAML에 고정되어 있다. 요약:

| ID | 사례 | expected_trajectory |
|---|---|---|
| TS01 | 안정적 PDL 증가 + DT 안정 | `stable_growth` |
| TS02 | PDL 증가 + DT 지속 악화 (P25:42h→P35:100h) | `progressive_slowdown` |
| TS03 | PDL 정지 | `plateau` |
| TS04 | plateau 후 관찰점 1개 회복 | `transient_recovery` |
| TS05 | plateau 후 2구간 이상 회복 | `recovery_after_plateau` |
| TS06 | 회복 후 재정지 | `re_arrest` |
| TS07 | DT와 PDL 방향 불일치 | `conflicting_trajectory` |
| TS08 | 시점 2개 이하 | `insufficient_series` |
| TS09 | snapshot(stable)과 raw series(worsening) 충돌 | `progressive_slowdown` + input_conflict |
| TS10 | 분화능 상실 동반 | `stable_growth` + `functionality_compromised` |
| TS11 | marker favorable + 지속 회복 | `recovery_after_plateau`, `possible_candidate` 가능 |
| TS12 | marker 결측 + 지속 회복 | `recovery_after_plateau`, `insufficient_evidence` 유지 |

> TS09가 핵심 성공 기준: P25:42h → P30:80h → P35:100h 에서 사용자가 `DT_trend=stable`이라고 적더라도
> 플랫폼이 raw series에서 `worsening`을 도출하고, snapshot을 조용히 덮어쓰지 않고 `input_conflict`로 명시해야 한다.
