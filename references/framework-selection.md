# Framework Selection

Run this step before slot extraction in `workflow.md §1`. The default LLM behaviour is to force every question into PICO, which often produces searches that miss relevant records when the question is exposure-based, qualitative, diagnostic, or scoping. Choose the framework once, deliberately, before extracting candidate slots.

Do not skip this step just because the topic looks like a clinical effectiveness question. The framework choice shapes which slots enter the concept gate and which are sensitivity-dangerous defaults.

## Framework selection table

| Question type | Typical framework | Notes |
|---|---|---|
| Intervention effectiveness | PICO | Population, Intervention, Comparator, Outcome. |
| Drug exposure, risk factor, aetiology, association | PECO | Population, Exposure, Comparator, Outcome. Comparator usually not searched. |
| Diagnostic accuracy | PIRD or diagnostic PICO | Population, Index test, Reference standard, Diagnosis/target condition. Reference standard usually not searched. |
| Prognosis | Population + prognostic factor + outcome | Comparator often absent. Validated prognosis filter may apply. |
| Prevalence / incidence | Condition + population + setting/context | Outcome may be prevalence itself. |
| Qualitative experience / views | PICo or SPIDER | Population, Interest/phenomenon, Context. SPIDER adds Design, Evaluation, Research type. |
| Scoping or mapping review | PCC | Population, Concept, Context. Often broader and less restrictive than intervention reviews. |
| Health services / intervention implementation | PICO, PCC, or SPIDER | Depends on review intent. |
| Methodological review | Custom concept framework | Usually method + domain/application. |

## Decision rule

1. Identify the question type from the table above. Use the user's plain-language question, not pasted Boolean syntax.
2. Choose the framework with the closest match.
3. State the framework choice and reason before extracting candidate slots in `workflow.md` section 1.
4. State whether a framework question is needed. If no framework question is needed, explicitly say `No framework question is needed` and give the reason. If a framework question is needed, ask only that question and stop.
5. If the question is ambiguous between two frameworks, prefer the framework that drops more sensitivity-dangerous concepts (e.g., PECO over PICO when Comparator would be irrelevant; PCC over PICO for scoping questions). When the ambiguity is high-impact (would change which concept enters the gate as essential), pause and ask the user before MeSH lookup, PubMed exploration, or block drafting.

## Sensitivity-dangerous defaults by framework

- **PICO**: Comparator and Outcome are usually omitted from the main search ([Frandsen et al. 2020](https://doi.org/10.1016/j.jclinepi.2020.07.005); [Ho et al. 2016](https://doi.org/10.1371/journal.pone.0167170)).
- **PECO**: Comparator is usually omitted. Outcome may be searched if it defines the disease endpoint and is reliably indexed; otherwise omit.
- **PIRD / diagnostic PICO**: Reference standard is usually omitted. Diagnostic accuracy terms (sensitivity, specificity) are usually omitted; use a validated diagnostic filter only if required.
- **PCC**: Context may or may not be searched. Do not over-restrict unless the context is central to scope.
- **PICo / SPIDER**: Context may or may not be searched. Qualitative study filters can reduce sensitivity if poorly designed.

In all cases, fewer required `AND` blocks generally protects recall. Carry the framework choice into the concept-analysis ledger in `concept-analysis-and-gating.md`.

## Recording the framework choice

Record the chosen framework, the question type, and the reason in the concept-analysis ledger. The ledger entry should include:

- chosen framework
- question type (from the table or `other - custom`)
- why this framework was chosen over the next-closest alternative
- which framework slots will be sensitivity-dangerous by default
- whether a framework question was needed, and why or why not
- the user/protocol answer when a framework question was asked

The framework choice and its rationale are decision-ledger items in the final audit Markdown.

## References

- Cooke A, Smith D, Booth A. Beyond PICO: the SPIDER tool for qualitative evidence synthesis. *Qualitative Health Research* 2012. [doi:10.1177/1049732312452938](https://doi.org/10.1177/1049732312452938).
- Frandsen TF, Nielsen MFB, Lindhardt CL, Eriksen MB. Using the full PICO model as a search tool for systematic reviews resulted in lower recall for some PICO elements. *J Clin Epidemiol* 2020. [doi:10.1016/j.jclinepi.2020.07.005](https://doi.org/10.1016/j.jclinepi.2020.07.005).
- Ho GJ, et al. Development of a Search Strategy for an Evidence Based Retrieval Service. *PLoS ONE* 2016. [doi:10.1371/journal.pone.0167170](https://doi.org/10.1371/journal.pone.0167170).
- Eriksen MB, Frandsen TF. The impact of patient, intervention, comparison, outcome (PICO) as a search strategy tool on literature search quality: a systematic review. *JMLA* 2018. [doi:10.5195/jmla.2018.345](https://doi.org/10.5195/jmla.2018.345).
- Campbell F, et al. Rapid reviews methods series: guidance on rapid scoping, mapping and evidence and gap map ('Big Picture Reviews'). *BMJ EBM* 2025. [doi:10.1136/bmjebm-2023-112389](https://doi.org/10.1136/bmjebm-2023-112389).
