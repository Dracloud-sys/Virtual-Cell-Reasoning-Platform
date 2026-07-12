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

## 2. 판정 우선순위

복합 trajectory를 단순 현재 상태로 덮어쓰지 않도록 crisis/recovery 계열을 먼저 탐지한다.

```
re_arrest → recovery_after_plateau → transient_recovery → plateau
→ progressive_slowdown → stable_growth → conflicting_trajectory → insufficient_series
```

---

## 3. 시계열 품질 검증 (오류 vs flag)

| 상황 | 처리 |
|---|---|
| 음수/0 이하 DT | 입력 오류 (모델 검증) |
| passage 중복 | 입력 오류 (모델 검증) |
| PDL 소폭 감소 | quality flag (`non_monotonic_pdl`) |
| 시점 2개 이하 | 입력 허용 + `insufficient_timepoints` |
| 일부 DT 누락 | 부분 계산 + `missing_dt` |
| 정렬되지 않은 입력 | 내부 정렬(원본 불변) |

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
