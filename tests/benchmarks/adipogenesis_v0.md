# 지방분화 판단 Benchmark v0
### VCRP 두 번째 vertical — adipogenesis reasoning이 반드시 맞혀야 하는 질문 10개

> 목적: full vertical이 **reasoning quality**를 유지하는지 고정한다. happy-path 테스트가 아니다.
> 위치: `tests/benchmarks/adipogenesis_v0.md` + `adipogenesis_v0.yaml`(하네스용)
> + `eval_adipogenesis_v0.py`(채점기) + `test_adipogenesis_eval.py`(회귀).

---

## 0. 이 benchmark가 존재하는 이유

두 번째 scorecard의 목적은 adipogenesis coverage를 늘리는 게 아니다.
**benchmark의 형태가 규칙이 전혀 다른 도메인으로 옮겨가는지**를 확인하는 것이다.

불멸화 benchmark는 "가능성을 판정으로 말하지 않는가"를 물었다.
지방분화 benchmark는 같은 질문을 다른 실패모드에 대해 묻는다 —
**marker panel을 지방세포로 읽는 것**, **배지에서 온 lipid를 분화로 읽는 것**,
**죽어가는 배양을 음성 결과로 읽는 것**. 셋 다 실제 프로그램에서 시간을 낭비시키는 오판이다.

---

## 1. 채점 구조 (hard 8점 + soft 4점 = 12점, 통과 ≥ 9)

| 축 | 배점 | 종류 |
|---|---|---|
| status 정확성 | 3 | hard |
| 금지 표현 부재 (assertion 필드 한정) | 3 | hard |
| 필수 flag 존재 | 1 | hard |
| 금지 flag 부재 | 1 | hard |
| 결측 축을 이름으로 호명 | 1 | soft |
| 제안된 실험이 보고한 불확실성을 겨냥 | 1 | soft |
| limitations를 암시가 아니라 명시 | 1 | soft |
| 양성 판정 시 maturity 미검증을 명시 | 1 | soft |

**hard 축은 하나라도 실패하면 그 문항 실패**다. soft 축은 점수만 잃는다 —
리포트가 "맞았지만 눈에 띄게 약한" 상태를 감추지 않기 위해서다.

금지 표현 검사는 불멸화 benchmark와 동일하게 **assertion 필드에만**
(`conclusion` + supporting/contradicting evidence, 즉 kernel의 `assertion_texts` 범위) 적용한다.
`limitations`는 스캔하지 않는다 — 그 필드는 금지 표현을 **금지하기 위해 인용**하기 때문이다.

---

## 2. status 어휘 (v0 = 5단계)

| status | 의미 |
|---|---|
| `differentiating` | commitment program + lipid 축적. **성숙 확정 아님** |
| `partially_differentiated` | 초기 program은 켜졌으나 late program이 **측정되었고 음성** |
| `not_differentiating` | program·lipid 모두 음성이고, 배양 건강이 confounder를 배제 |
| `differentiation_inhibited` | 억제 신호가 활성이고 program이 시작되지 않음 |
| `insufficient_evidence` | 필수 축 결측, 상충, 또는 배양 건강이 판단을 막음 |

**없는 두 개가 있는 것만큼 중요하다.**
`mature`는 없다 — marker panel로 성숙을 증명하는 것이 이 vertical이 금지하는 바로 그 과해석이다.
"culture compromised"도 없다 — 생존율 저하는 *다른 생물학적 상태*가 아니라 **판단 불가**이므로
`insufficient_evidence` + flag로 보고한다.

---

## 3. 실행 경로 — 10문항 전부 제품 경로 (PR10b 선례)

```text
seed 그래프 → AdipogenesisDomainPack.execute(query, store) → ReasoningResponse 채점
```

* 채점기는 `assess()`나 report builder를 **직접 부르지 않는다**. dispatch 권한은 pack에만 있다.
* intent는 *채점 축*만 고른다(기전 질문에는 status 축이 없음).
* 회귀 고정: 호출 카운팅 spy + import 가드(`test_adipogenesis_eval`).

---

## 4. 질문 10개 — 각 문항이 지키는 것

| id | 시나리오 | 기대 | 지키는 규칙 |
|---|---|---|---|
| ADI-Q1 | 완전한 program + lipid | `differentiating` | 명백한 양성에서도 성숙을 주장하지 않는다 |
| ADI-Q2 | marker 5개 양성, lipid 미측정 | `insufficient_evidence` | **marker panel은 지방세포가 아니다** — 이 도메인 최다 과해석 |
| ADI-Q3 | program·lipid 음성, 배양 건강 | `not_differentiating` | 진짜 음성. confounder가 배제되어야 음성을 말한다 |
| ADI-Q4 | 억제 활성, program 미시작 | `differentiation_inhibited` | 억눌린 것과 무반응은 다음 실험이 다르다 |
| ADI-Q5 | 억제 활성 + 부분 program | `partially_differentiated` | 억제 보고가 program이 시작된 증거를 지우지 않는다 |
| ADI-Q6 | program 없이 lipid | `insufficient_evidence` + 상충 | 배지 artifact가 결과로 승격되는 경로를 막는다 |
| ADI-Q7 | 사실상 미측정 | `insufficient_evidence` | 침묵에서 판정을 만들지 않고, 결측 축을 전부 호명한다 |
| ADI-Q8 | 형태만 양호 | `insufficient_evidence` | 형태는 보강하고 결정하지 않는다 — 사진은 assay가 아니다 |
| ADI-Q9 | 죽어가는 배양 | `insufficient_evidence` | "분화 안 함"과 "죽는 중"은 panel에서 동일하게 보인다 |
| ADI-Q10 | 기전 설명 | status 없음 | 구동/억제 **양쪽 arm**이 모두 나와야 한다 |

Q3와 Q9는 **생존율 하나만 다르다.** 그 차이가 판정을 바꾸지 않으면 이 vertical은 실패다.

---

## 5. 금지 표현

`mature adipocyte`, `fully differentiated`, `terminally differentiated`,
`transdifferentiation`, `proves the cells are fat`, `ready for harvest`,
`suitable for consumption`, `food safe`.

뒤의 셋은 배양육 맥락에서 이 리포트가 **절대 답하지 않는** 질문이다.
분화 판정은 식품 안전성·수확 적기에 대해 아무것도 말하지 않는다.

---

## 6. 현재 결과

10/10 통과, 9문항 만점(12/12), ADI-Q1도 `maturation_unverified`를 명시하여 12/12.

> `maturation_unverified`는 ADIPOQ/PLIN1이 **high여도** 양성 판정에서 항상 붙는다.
> 거기서 flag를 억제하면 "marker 양성 = 성숙 검증"이라는 함의가 생기는데,
> 이 vertical은 지방세포의 *기능*을 측정하지 않으며 성숙은 기능으로만 답할 수 있다.
> 이 규칙은 benchmark의 soft 축이 처음 감점하면서 드러났다 —
> benchmark-first가 다시 한 번 설계 결함을 먼저 잡은 사례.
