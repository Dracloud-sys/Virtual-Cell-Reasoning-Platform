# Scientific Evidence Policy

A core commitment of this platform: **established knowledge, evidence-supported
hypotheses, and speculation are never mixed.** This is enforced in code, not just
in documentation.

## The three tiers

```python
class EvidenceTier(StrEnum):
    ESTABLISHED = "established"   # well-supported, textbook / curated-database biology
    HYPOTHESIS  = "hypothesis"    # plausible, backed by some evidence but not settled
    SPECULATIVE = "speculative"   # model-generated conjecture, unverified
```

## Rules

1. **Every biological statement produced by code is a `Claim`** carrying exactly one
   `EvidenceTier`.
2. **Never upgrade a tier implicitly.** A hypothesis does not become established
   because a model is confident. Tier changes require explicit new evidence.
3. **Cite and state assumptions.** `Claim` carries `citations` and `assumptions`
   fields; established claims should reference a source, speculative claims should
   list the assumptions they rest on.
4. **Confidence ≠ tier.** A numeric confidence (0–1) expresses uncertainty *within*
   a tier. A speculative claim can have high internal confidence and still be
   speculative.
5. **Validation Agent** checks that outputs respect these rules before they are
   surfaced to the user.

## Why enforce in code

Conflating these categories is the most common failure mode of AI systems in
biology. By making the tier a required, typed field on every claim, the platform
makes it structurally impossible to emit an untiered biological statement.
