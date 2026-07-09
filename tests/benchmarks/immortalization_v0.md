# 불멸화 판단 Benchmark v0
### VCRP Phase 0 산출물 — 세포공학 reasoning이 반드시 맞혀야 하는 질문 10개

> 목적: 코드를 고치기 **전에**, VCRP가 일관되게 답해야 하는 불멸화 판단 질문을 고정한다.
> 위치: `tests/benchmarks/immortalization_v0.md` + `immortalization_v0.yaml`(하네스용).
> 리뷰 반영: candidate_status **3단계**로 축소, **rule-based baseline 우선**, 각 질문에 **intent/entity/risk annotation**, trend 질문은 v0에서 제한적 답변으로 분류.

---

## 0. 이 benchmark의 채점 철학

VCRP의 가치는 "TERT가 뭐야"에 답하는 게 아니라, **복합 marker를 근거등급을 지키며 판단하고, 과해석을 스스로 막고, 다음 실험으로 연결하는가**에 있다. 따라서 좋은 답은 다음을 모두 만족한다.

1. 단일 marker가 아니라 **2~4개 지표를 함께** 해석한다.
2. supporting **과** contradicting 근거를 동시에 제시한다.
3. "가능성"을 "판정"으로 말하지 않는다(overinterpretation risk 명시).
4. 답이 **next experiment**로 이어진다.
5. species/cell-type 적합성을 반영한다(bovine primary ≠ 3T3-L1/human).
6. 근거등급을 지킨다(hypothesis를 established로 승격하지 않음).

---

## 1. candidate_status 어휘 (v0 = 3단계)

| status | 의미 |
|---|---|
| `possible_candidate` | 증식 지속 + senescence 신호 낮음. 단, **불멸화 확정 아님**, 추가 검증 필요 |
| `senescence_or_stress_prone` | senescence/DNA damage/stress 신호 우세 |
| `insufficient_evidence` | 판단에 필요한 핵심 축(특히 PDL trend + senescence marker 중 하나 이상)이 없음 |

> v1 확장 예정: `weak / possible / strong / unstable-crisis / senescence-prone`. **v0에서 5단계로 나누면 데이터 부족 상태에서 오히려 과해석 위험이 커지므로 3단계로 시작한다.**
>
> 직교 flag(status와 별개로 `DecisionReport`에 실림): `functionality_compromised`(분화능 상실), `trend_needed`(단일 시점만으로 부족).

---

## 2. Rule-based baseline (LLM보다 먼저 구현)

LLM이 이상한 판단을 했을 때 이걸로 검증한다. 결정적(deterministic) 하한선.
구현: `src/virtualcell/agents/immortalization/baseline.py` (`baseline_status`).

```python
def baseline_status(m: dict) -> tuple[str, list[str]]:
    """m: marker dict. 값은 'high'/'low'/'increasing'/'plateau'/'stable'/'worsening'/'unknown'/None."""
    flags = []
    UNK = (None, "unknown")
    senescence_axes = ["gammaH2AX", "SA_b_gal", "p16", "p21"]
    measured_sen = [a for a in senescence_axes if m.get(a) not in UNK]

    # 기능적 stress 신호는 분자 marker 없이도 성립(DT 악화·PDL 정체 자체가 신호)
    functional_stress = m.get("PDL_trend") == "plateau" or m.get("DT_trend") == "worsening"
    molecular_sen = any([
        m.get("gammaH2AX") == "high", m.get("SA_b_gal") == "high",
        m.get("p16") == "high", m.get("p21") == "high",
    ])
    sen_signal = functional_stress or molecular_sen

    # 증식 신호: PDL↑ + γH2AX 낮음 + DT 안정/개선 (강한 3중 조건)
    pro_signal = (
        m.get("PDL_trend") == "increasing"
        and m.get("gammaH2AX") == "low"
        and m.get("DT_trend") in ("stable", "improved")
    )

    # 직교 flag
    if m.get("adipogenic_retention") == "lost":
        flags.append("functionality_compromised")
    if m.get("DT_trend") == "worsening" and m.get("PDL_trend") == "increasing":
        flags.append("trend_needed")

    # 판정: senescence/stress 우선 → possible → insufficient
    if sen_signal and not pro_signal:
        return "senescence_or_stress_prone", flags
    # possible_candidate: 강한 증식 신호 + 최소 1개 favorable 분자 축(γH2AX low가 이미 pro_signal에 포함)
    if pro_signal and len(measured_sen) >= 1:
        return "possible_candidate", flags
    # PDL trend 없음, 또는 분자 축도 기능적 stress도 전무 → 판단 불가
    return "insufficient_evidence", flags
```

LLM 답변의 `candidate_status`가 baseline과 불일치하면 rubric에서 감점하고 사람이 리뷰한다.

> **self-check(회귀):** 위 baseline을 10개 시나리오에 돌려 `expected_status`/`expected_flags`와 대조한 결과 status 8/8, flag 전부 일치(기전 질문 Q5·Q6 제외). 이 정합성을 CI 회귀 테스트로 고정한다. *참고: 초안 baseline은 possible_candidate 임계값(≥2)과 "기능적 stress를 분자 marker 없이는 무시"하는 두 오류가 있었고, 이 self-check가 Q2·Q3·Q7 불일치로 그것을 드러내 교정했다 — benchmark-first가 실제로 설계 결함을 먼저 잡은 사례.*

---

## 3. 채점 rubric (질문당 6축 × 0/1/2점, 만점 12, 통과 ≥ 9)

| 축 | 0점 | 1점 | 2점 |
|---|---|---|---|
| **status 정확성** | 틀린 status | baseline과 방향은 맞으나 flag 누락 | baseline과 일치 + flag 정확 |
| **marker 통합** | 단일 marker 의존 | 일부만 통합 | 관련 2~4개 지표 함께 해석 |
| **양측 근거** | 한쪽만 | supporting만 충분 | supporting+contradicting 모두 |
| **과해석 통제** | 가능성을 판정처럼 | 위험 언급은 있으나 모호 | 해당 질문의 구체적 risk 명시 |
| **검증 제안** | 없음/무관 | 일반적 제안 | 결핍 축을 직접 겨냥한 실험 |
| **근거등급 규율** | hypothesis를 established로 | tier 일부 흐림 | tier 정확 + species/cell-type 반영 |

`overcalling_immortalization`(가능성을 불멸화로 단정)은 **어느 축에서든 발생 시 해당 질문 자동 0점 처리** 후 사람 리뷰 — 이게 이 도메인의 최우선 실패모드다.

---

## 4. 질문 10개 (annotation + scenario + 정답 skeleton)

> 각 질문의 `scenario`는 합성 예시다(실제 회사 데이터 아님). 값은 `high/low/increasing/plateau/stable/worsening/unknown`으로 단순화.

기계 판독 spec은 [`immortalization_v0.yaml`](immortalization_v0.yaml)에 있다. 아래는 각 질문의 정답 skeleton(사람 채점용).

### Q1 — γH2AX↑ + PDL 정체 → `senescence_or_stress_prone`
- supporting: PDL 정체 + DT 악화 + γH2AX high + SA-β-Gal high → replicative senescence 진입 신호. (established)
- contradicting: p16/p21 미측정으로 senescence 확정은 불가.
- overinterpretation_risk: **폐기 오판 주의.** bovine fibroblast는 자발적 불멸화가 장기 배양 후 늦게(수백 일) 나타난 사례가 보고됨 → 정체 = 사망으로 단정 금지. (hypothesis)
- next_experiment: p16/p21 qPCR, telomere length, SASP 프로파일; 장기 tracking 유지.

### Q2 — PDL↑ + γH2AX↓ (핵심 축 일부 결측) → `possible_candidate`
- supporting: PDL 증가 + DT 안정 + γH2AX 낮음 → 증식 지속/DNA damage 낮음.
- contradicting: p16/p21/SA-β-Gal 미측정, telomere/TERT 활성 미확인 → 불멸화 확정 근거 없음.
- overinterpretation_risk: **PDL↑ + γH2AX↓만으로 불멸화 단정 금지.** 일시적 증식 회복일 수 있음.
- next_experiment: p30–p50 장기 PDL tracking, SA-β-Gal, p16/p21 qPCR, telomere/TERT 활성.

### Q3 — PDL↑ 이지만 DT 악화 (trend) → `senescence_or_stress_prone` + `trend_needed`
- supporting: DT 42→58→80h 지속 악화 → senescence 접근 신호. PDL 증가는 둔화 중.
- contradicting: senescence marker(γH2AX/SA-β-Gal/p16) 직접 측정 없음.
- overinterpretation_risk: **단일 시점 금지.** PDL이 아직 오른다고 안정으로 오판 말 것 — 추세가 핵심.
- next_experiment: γH2AX/SA-β-Gal, DT 시계열 계속, 밀도 통제 DT assay(contact inhibition 배제).

### Q4 — SA-β-Gal↑ + p16↑ → `senescence_or_stress_prone`
- supporting: SA-β-Gal high + p16(CDKN2A) high + PDL 정체 → p16-매개 senescence. (established)
- contradicting: 단일 시점, γH2AX 미확인.
- overinterpretation_risk: SA-β-Gal 단독은 위양성 가능(고밀도/과컨플루언시) → p16과 함께라 신뢰 상승했지만 밀도 조건 확인 필요.
- next_experiment: γH2AX IF, PDL 추세, 밀도 통제 재염색.

### Q5 — TERT 단독 (기전 질문, status 없음)
- mechanistic_chain: TERT → telomere maintenance → replicative(telomere) senescence 지연. (established)
- limitation: **TERT는 p16/RB checkpoint를 우회하지 못함.** p16이 높은 primary cell은 TERT 단독으로 불멸화 실패가 흔함 → CDK4 필요. (established)
- next_experiment: p16 상태 확인, telomere/TERT 활성, 필요 시 CDK4 병용.

### Q6 — TERT + CDK4 (기전 질문, status 없음)
- mechanistic_chain: TERT → telomere maintenance(replicative senescence 방지) **+** CDK4 → p16-매개 senescence를 G1/S로 우회 → 지속 증식. 비-oncogenic·재현성 높은 경로로 보고됨(예: bovine iBSC >120 doublings). (established)
- caveat: 불멸화 ≠ 안전·기능 보장. genomic stability, 분화능(cultured meat에선 필수)을 별도 확인.
- next_experiment: karyotype/genomic stability, 분화 assay(근/지방), 장기 PDL.

### Q7 — γH2AX↓·증식 지속 이지만 분화능 상실 → `possible_candidate` + `functionality_compromised`
- supporting: 증식 지속 + γH2AX 낮음 → 불멸화 축은 긍정적.
- contradicting: PPARG/CEBPA/FABP4 하향 + Oil Red O 약함 → **분화능 상실**. cultured meat 목적에는 부적합할 수 있음.
- overinterpretation_risk: **불멸화와 유용성을 혼동 금지.** 증식이 좋아도 지방/근육 분화가 안 되면 제품 목적 미달.
- next_experiment: 분화 프로토콜 재검(OA delivery/maturation/staining 조건), 초기 passage 분화능과 비교, marker 시계열.

### Q8 — 핵심 축 미측정 → `insufficient_evidence`
- missing_axes: senescence marker(γH2AX/SA-β-Gal/p16/p21) 전무 → 증식 지표만으로 판단 불가.
- overinterpretation_risk: PDL↑ + DT 안정만으로 후보 단정 금지.
- next_experiment: γH2AX IF, SA-β-Gal, p16/p21 qPCR 우선 측정.

### Q9 — PGC1A/TERT 자발적 경로 (약한 근거 + P53 표현 주의) → `insufficient_evidence`
claim을 반드시 분해할 것(과해석 방지):
- Claim 1 (established): TERT activation은 telomere maintenance와 연관.
- Claim 2 (established): PGC1A activation은 mitochondrial 기능 회복과 연관.
- Claim 3 (hypothesis, **citation 필수**): 보고된 자발적 불멸화 경로는 **"P53 활성화 없이(without activating P53, P53-independent)"** 진행된 것으로 기술됨(Believer Meats, Nature Food 2025). "P53 없이/P53 loss"로 바꿔 말하지 말 것.
- Claim 4 (hypothesis): TERT/PGC1A 연관 회복은 자발적 불멸화 관련 기전을 **시사(SUGGESTS)**할 수 있음. `CAUSES` 금지.
- KG edge는 `ASSOCIATED_WITH`/`SUGGESTS`.

### Q10 — 상충 marker (양측 근거 동시 출력) → `insufficient_evidence` / `senescence_or_stress_prone`
- **핵심은 상충을 억지로 하나로 뭉개지 않는 것.**
- supporting(증식): PDL 증가, SA-β-Gal 낮음.
- contradicting(stress): γH2AX high + p21 high → DNA damage response 활성. 단 p16 정상.
- conflict_explanation: γH2AX/p21↑(급성 DNA damage 축)과 SA-β-Gal↓·p16 정상(만성 senescence 축)이 불일치 → 급성 stress vs 확립된 senescence 구분 필요.
- next_experiment: 시간차 재측정(회복 여부), p16 재확인, γH2AX foci 정량, DNA damage 유발원 점검.

---

## 5. 2주 prototype 성공 기준 (좁힘)

> 합성 예시 데이터를 입력하면, `ImmortalizationAssessmentAgent`(먼저 **rule-based**)가 `DecisionReport` 형식으로 `possible_candidate / senescence_or_stress_prone / insufficient_evidence` 중 하나를 판정하고, 그 근거(supporting+contradicting)·overinterpretation risk·다음 검증 실험을 출력한다. Q1–Q10 중 rule-based가 baseline과 일치해야 하는 항목을 **회귀 테스트로 고정**한다. LLM synthesis 연결은 그 다음.

Phase 2 분할: `2-a DecisionReport 모델 → 2-b explain→DecisionReport 포맷팅 → 2-c seed graph → 2-d rule-based agent → 2-e LLM synthesis`.
