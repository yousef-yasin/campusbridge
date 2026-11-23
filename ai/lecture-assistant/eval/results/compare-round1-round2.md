# Round 1 vs round 2

Round 1: the first run (`round1.*`, scored with the round-1 rules). Round 2: glossary version 2 and the
general scoring rules of `CHANGES.md`. «Round 1 rescored» scores the round-1 answers again with the
round-2 rules (no new run), to separate the scoring change from the assistant change.

| Measure | Round 1 | Round 1 rescored | Round 2 |
|---|---|---|---|
| Decision accuracy | 97% | 97% | 97% |
| Refusal precision | 88% | 88% | 88% |
| Refusal recall | 100% | 100% | 100% |
| Hit@1 | 76% | 76% | 76% |
| Hit@5 | 100% | 100% | 100% |
| Complete answers | 60% | 76% | 76% |
| Correct sources | 100% | 100% | 96% |
| needs_review | 0 | 0 | 1 |
| Mean time (s) | 7.4 | 7.4 | 12.3 |
| Unavailable | 0 | 0 | 0 |
| Chunks from a course not allowed | 0 | 0 | 0 |

## By question type

| Type | n | Decision 1 → 2 | Hit@1 1 → 2 | Hit@5 1 → 2 | Complete 1 → 2 |
|---|---|---|---|---|---|
| text | 12 | 100% → 100% | 75% → 75% | 100% → 100% | 50% → 92% |
| visual | 4 | 100% → 100% | 100% → 100% | 100% → 100% | 100% → 100% |
| cross_language | 5 | 80% → 80% | 80% → 80% | 100% → 100% | 60% → 60% |
| not_found | 5 | 100% → 100% | - → - | - → - | - → - |
| follow_up | 2 | 100% → 100% | 0% → 0% | 100% → 100% | 50% → 0% |
| colloquial | 2 | 100% → 100% | 100% → 100% | 100% → 100% | 50% → 50% |
| permission | 2 | 100% → 100% | - → - | - → - | - → - |

## Questions that changed, or that still fail

| ID | Status 1 → 2 | Rank 1 → 2 | Complete 1 → (1 rescored) → 2 | Still missing in round 2 |
|---|---|---|---|---|
| T01 | answered → answered | 2 → 2 | no → (no) → no | σ / √n; population standard deviation | standard deviation of the whole population |
| T02 | answered → answered | 1 → 1 | no → (yes) → yes | - |
| T05 | answered → answered | 1 → 1 | no → (no) → yes | - |
| T07 | answered → answered | 1 → 1 | no → (yes) → yes | - |
| T08 | answered → answered | 1 → 1 | no → (yes) → yes | - |
| T10 | answered → answered | 1 → 1 | no → (yes) → yes | - |
| A04 | not_found → not_found | 1 → 1 | no → (no) → no | biopsy; small tissue sample | عينة صغيرة من النسيج | عينة نسيج |
| A05 | answered → answered | 1 → 1 | no → (no) → no | phishing |
| F01 | answered → answered | 2 → 2 | yes → (yes) → no | 73.06 |
| F02 | answered → needs_review | 2 → 2 | no → (no) → no | Denial-of-Service; flooding | traffic | إغراق |
| D02 | answered → answered | 1 → 1 | no → (no) → no | subset; broadest umbrella | all forms of information; encryption | data masking | data loss prevention |
