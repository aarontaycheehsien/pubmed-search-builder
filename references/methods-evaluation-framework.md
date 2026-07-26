# Methods-Evaluation Framework

Use this profile when the review asks how well a technology, tool, or method performs a task, rather than whether a health intervention works. Read it during framework selection, before slot extraction in `concept-analysis-and-gating.md`.

PICO forces these questions into a shape they do not have: the "population" is a task, the "intervention" is a tool, the "comparator" is usually a human baseline that abstracts rarely name as a contrast, and the "outcome" is a performance metric. Requiring all four as `AND` blocks produces a precise search that misses most eligible evaluations.

## Trigger

Route to this profile when the plain-language question has this shape:

> How well does [method/tool] perform [task] in [application context], compared with [baseline]?

Typical instances: large language models generating Boolean search strategies; AI-assisted title/abstract screening; automated risk-of-bias assessment; a clinical search filter's retrieval performance; machine-learning triage of imaging studies.

The trigger is the question's shape, not its subject matter. A question about a tool's *effect on patients* is an intervention question and belongs in PICO. A question about a tool's *task performance* belongs here.

## Canonical slot profile

| Slot | Slot ID | Default search handling |
|---|---|---|
| Technology or method under evaluation | `technology_method` | Usually essential |
| Task or function performed | `task_function` | Essential if it defines scope; broaden when terminology is fragile |
| Application context or domain | `application_context` | Essential only when definitional and searchable |
| Comparator or baseline | `comparator` | Screening-only by default |
| Performance outcome | `performance_outcome` | Screening-only by default |

All five slots must be named in the protocol even when three of them are never searched. Naming a slot and then assigning it to screening is a recorded decision; omitting the slot hides it.

Defaults are starting positions, not conclusions. Each one still passes through the `AND`-block admission test and the fragility rubric in `concept-analysis-and-gating.md`, and any departure from a default needs a recorded reason.

A slot may carry more than one element, and those elements may need opposite handling. Split them and record each separately rather than forcing one decision. In particular, a database, platform, or interface named in the question — MEDLINE, Ovid, PubMed — is an eligibility property, not searchable context: requiring it drops multi-database evaluations, and `OR`-ing it into a block pulls in every paper that merely reports searching there.

When the method and the task are the same artifact, merge them into one block and record why. A search filter *is* a retrieval instrument, so filter, hedge, search, and retrieval language is one vocabulary family; splitting it across `technology_method` and `task_function` manufactures a near-duplicative second `AND` block and costs recall. The five slots are analytic roles, not a required block count.

### The fragility rubric applies to the paper's subject, not its study properties

The rubric in `concept-analysis-and-gating.md` lists eligibility properties, bias/risk judgments, and outcome-like qualifiers as hard red flags forcing `very_fragile`, and its examples name concepts "usually judged during screening or risk-of-bias assessment". Those flags describe concepts a screener judges *about* a study. Under this profile the method and the task are what the paper is *about* — a review of automated risk-of-bias tools has risk-of-bias assessment as its topic anchor, not as a study property. Score `technology_method` and `task_function` on terminology stability, indexing, and retrieval behaviour as normal; the red flag still fires on `comparator` and `performance_outcome`, which remain properties of the evaluated study.

### Why comparator and performance outcome default to screening-only

Evaluations report a comparator and a metric in their results, not usually as indexed topic anchors, and the wording varies without limit: recall, sensitivity, precision, positive predictive value, agreement, F1, workload saved, time saved, error rate. Requiring either as an `AND` block is the outcome/comparator recall loss documented in `framework-selection.md`, applied to a literature that is less consistently indexed than trials. Both are eligibility properties to verify at screening.

### Task-language breadth

`task_function` is where this profile most often fails. The exact phrasing in the user's question ("Boolean search strategy generation") is usually one of several labels for the same task, and authors frequently describe the operation without naming it. Apply the scope breadth check in `concept-analysis-and-gating.md`: if a broader workflow concept is plausibly in scope, make the broader concept the main block and keep the narrow phrasing as a within-block term family or a focused variant. Do not let a single brittle expression carry the block.

A stage named in the plain-language question is not by itself the protocol narrowing the review. The breadth check defers to an explicit protocol restriction; a question that says "for title/abstract screening" has usually named the *purpose* the method serves, not restricted the *task* the method performs. Resolve it with ambiguity check 2 below: narrow the block only when the named stage is what the method does. Where the reading is material and no protocol settles it, ask.

### Is the application context definitional?

`application_context` is searched only when it is definitional, which is a concrete test: would a record about the same method performing the same task in a different domain be out of scope? If yes, the context is definitional and may be searched. If it would still be eligible, the context is a within-block tethering family or a screening property.

Tethering is the common case. When the task word is generic — "screening" retrieves cancer, newborn, and drug screening — the context is what makes it tractable, and it belongs inside the task block as `OR`-ed terms rather than as a third required `AND` block.

## Mandatory ambiguity check

Resolve all three before assigning roles. Each is high-impact: getting one wrong changes which concept enters the gate as essential.

1. **Is the method performing the task, or being evaluated at it?** A study where an LLM is used as a labour-saving device inside someone else's review is not the same as a study measuring how well the LLM performs. Both may be eligible, but only the second is guaranteed to name performance language. Decide which is in scope before deciding whether `performance_outcome` is searchable.

2. **Which workflow stage is in scope?** Search-strategy generation, database searching, title/abstract screening, full-text screening, study selection, data extraction, risk-of-bias assessment, synthesis, and report drafting are distinct tasks with distinct vocabularies. A question about one stage must not silently acquire the others, and a question about the whole workflow must not be narrowed to one stage.

3. **Is evidence synthesis the application context or the eligible report type?** "LLMs for systematic review searching" describes where the method is applied. It does not make systematic reviews the records being sought. The eligible records are primary methods-evaluation studies. Confusing the two attaches a review-report retrieval profile to a primary-studies protocol and discards the evaluations the review is about.

If any of these cannot be resolved from the question or protocol, pause and ask the user before MeSH lookup or block drafting.

## Worked example

Question: *How well do LLMs generate Boolean search strategies for title/abstract screening in systematic reviews?*

| Slot | Element | Handling |
|---|---|---|
| `technology_method` | Large language models | Essential `AND` block |
| `task_function` | Literature-search / evidence-synthesis workflow | Essential `AND` block, broadened from the narrow action |
| `task_function` | Boolean strategy generation — the narrow action wording | Within-block term family, and a focused variant |
| `application_context` | Systematic reviews, and the title/abstract-screening purpose the strategy serves | Screening-only |
| `comparator` | Human or expert searcher baseline | Screening-only |
| `performance_outcome` | Recall, precision, strategy quality, workload | Screening-only |

`task_function` carries two rows because the breadth decision lives inside that slot: the broad workflow is the block, and the narrow wording the question actually used is kept as vocabulary and as a prioritization strand. This is the multiple-elements-per-slot case above, not a sixth slot.

Evidence target: primary methods-evaluation studies. Systematic reviews are the setting the method is applied to, not the records being retrieved.

The result is a two-block recall-first main strategy — method `AND` workflow — with the narrow Boolean-generation phrasing carried as a focused variant for prioritized screening. It is not a five-block search.

## Evidence target

Set `evidence_target` explicitly whenever this profile is selected; lock validation requires it.

- `primary-studies` is the normal mode. It includes primary methodological evaluations: an experiment measuring how an LLM performs at screening is a primary study, not a review, even though its subject matter is review methodology.
- Choose `evidence-syntheses` or `mixed` only when completed syntheses are themselves the records being sought — for example, a review of published systematic reviews of AI screening tools. The application context never triggers this mode on its own.
- The conditional review-discovery gate and the retrieval profile in `evidence-synthesis-retrieval.md` activate from `evidence_target.mode` alone. Do not compile a review-retrieval profile because systematic reviews appear in the question.

`methods_papers` handling deserves an explicit decision here rather than a default: in this profile the methods paper is often the target, not noise.

## Protocol encoding

Declare the profile in the review protocol so the choice is machine-checkable rather than prose-only:

```json
"review": {
  "question": "How well do LLMs generate Boolean search strategies for systematic reviews?",
  "framework": {
    "name": "Methods evaluation",
    "profile_id": "methods-evaluation",
    "rationale": "Task-performance question about a tool, not an intervention effect.",
    "slots": [
      {"id": "technology_method", "label": "Technology or method", "description": "..."},
      {"id": "task_function", "label": "Task or function", "description": "..."},
      {"id": "application_context", "label": "Application context", "description": "..."},
      {"id": "comparator", "label": "Comparator or baseline", "description": "..."},
      {"id": "performance_outcome", "label": "Performance outcome", "description": "..."}
    ]
  }
}
```

`profile_id` is optional and additive: protocols without it keep their existing validation and compile output unchanged. When it is present, lock validation requires all five canonical slot IDs and an explicit `evidence_target`. Slot labels and descriptions stay free text; only the IDs are fixed. See `protocol-dsl.md`.

## Compiled QA and audit

Compilation adds a `methods-evaluation-role-safety` domain to the critic packet and a "Methods-evaluation framework decisions" section to the audit outline. The critic must answer, with evidence:

- were `comparator` or `performance_outcome` concepts turned into required `AND` blocks without a recorded justification?
- was the task narrowed to one brittle expression when a broader workflow concept was plausibly in scope?
- was the application context confused with a publication type or report filter?
- was study-design or "evaluation" terminology used as an unvalidated filter?
- does a focused task-specific variant attempt to replace the recall-first main strategy?

The compiled packet carries the observed slot-to-concept assignments so these questions are answered against the protocol, not from memory. Record the resolved answers in the audit's methods-evaluation section alongside the concept ledger.

## References

- Frandsen TF, Nielsen MFB, Lindhardt CL, Eriksen MB. Using the full PICO model as a search tool for systematic reviews resulted in lower recall for some PICO elements. *J Clin Epidemiol* 2020. [doi:10.1016/j.jclinepi.2020.07.005](https://doi.org/10.1016/j.jclinepi.2020.07.005).
- Ho GJ, et al. Development of a Search Strategy for an Evidence Based Retrieval Service. *PLoS ONE* 2016. [doi:10.1371/journal.pone.0167170](https://doi.org/10.1371/journal.pone.0167170).
- Booth A. Clear and present questions: formulating questions for evidence based practice. *Library Hi Tech* 2006. [doi:10.1108/07378830610692127](https://doi.org/10.1108/07378830610692127).
