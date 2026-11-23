# Changes to the evaluation

Every change to the questions, the scoring or the assistant between rounds, and why.
Results of a round are never edited: `results/round1.*` is the first run exactly as it came out
(only the files were renamed from `eval-20261123T235021.*`).

## Round 1 → round 2 (2026-11-24)

### Scoring (general rules, not per question)

1. **A glossary term also counts in Arabic.**
   - **The rule:** an item of `must_include` or `any_of` that is a term of the shared glossary
     (`ai/shared/glossary/terms.json`) is also found when the answer has its Arabic meaning or
     an accepted wording. The comparison is the glossary's own: without diacritics, ال or hamza
     forms.
   - **Why:** answers in `ar` and `mixed` modes translate terms. In round 1, translations were
     scored as missing even when they were exact: for example «التهاب الكبد B وC» for hepatitis.
   - **Limit:** terms outside the glossary are still required as written. In round 1 these
     failed only because they were translated: digital signatures, change control, phishing,
     population standard deviation, subset.

2. **What the question did not ask for is not required.**

   | Question | Removed | Why |
   |---|---|---|
   | T07 | `any_of: ["2020"]` | The question asks which type of attack SolarWinds was, not when it happened. |
   | T08 | `any_of: ["1970s"]` | The question names the era («mainframe days») and asks what security was about, not when the era was. |
   | T02 | `must_include: ["0.40033"]`, moved into the `any_of` group with `40.03%` | One probability is asked. 0.40033 and 40.03% are the same fact in two forms; requiring both asked for a second form the student did not ask for. |

   All 32 questions were checked against this rule. The others ask for every required item.
   - **A05 keeps «phishing»:** the lecture defines the two kinds of insider threat by their
     examples.
   - **F02 keeps «flooding»:** it is the example the question asks for.

3. **D02 stays as it is.** The answer explains the scope of InfoSec and of data security, but
   leaves out data security's tools (encryption, data masking, DLP), which the comparison on
   page 10 includes. It stays incomplete.

`questions.json` is now version 2.

### Assistant: shared glossary version 2

- **Added:** 12 health terms of `Cancer_Awareness_English.docx` (domain `health`). Each term
  appears in that file.
  - biopsy = الخزعة
  - metastasis = النقائل
  - screening = الفحص المبكر
  - diagnosis = التشخيص
  - early detection = الكشف المبكر
  - risk factors = عوامل الخطر
  - warning signs = العلامات التحذيرية
  - human papillomavirus / HPV = فيروس الورم الحليمي البشري
  - hepatitis = التهاب الكبد
  - second-hand smoke = التدخين السلبي
  - cancer = السرطان
- **Why:** A04 («ما هي الخزعة…») was refused in round 1 before the model was called.
  - Best similarity was 0.667, under the 0.68 threshold.
  - Word coverage was 0, because «الخزعة» had no glossary link to "biopsy".
  - With the glossary, the question is expanded with "biopsy" like the other terms.
- **Version:** a new sealed version, version 2 with a new sha256, as the glossary rules
  require.
  - HPV has kind `acronym_letters`, a kind the speech-to-text loader accepts. Its test still
    loads the file.
  - The meanings are a draft for review by the course instructors, like the rest of the
    glossary.
- **Not changed:** the thresholds (`min_similarity` 0.68, `min_coverage` 0.6), the prompt, the
  models and every other setting.

### Index

Round 1 already ran on the index without title pages and university IDs, and round 2 uses the
same index.
