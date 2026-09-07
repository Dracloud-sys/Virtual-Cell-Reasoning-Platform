## Summary

<!-- What does this PR change and why? -->

## Roadmap stage

<!-- Which stage in docs/roadmap.md does this relate to? -->

## Verification

<!--
Evidence, not assertion. A reviewer should be able to tell which commit was tested without
asking. "Everything passes" is not a verification result.
-->

- Base / head SHA:
- `python scripts/verify.py`:
- Scorecards: immortalization __/10 · adipogenesis __/10 · validation loop __/6 · genome editing __/10
- Per-question scores vs base: <!-- identical, or the explanation for each one that moved -->
- Kernel diff: <!-- 0 lines vs <base>, or the authorization that permits it -->

Anything skipped is named here rather than counted as passing.

## Checklist

- [ ] `python scripts/verify.py` passes in full (not a hand-assembled subset)
- [ ] Tests added/updated
- [ ] New biological claims carry an `EvidenceTier`
- [ ] Existing claim text, tiers, citations and confidences are unchanged, or the change is
      argued above with its literature grounding
- [ ] Docs updated if behavior changed
