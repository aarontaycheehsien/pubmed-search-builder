# Workflow

Use this detailed workflow when constructing a new high-sensitivity PubMed strategy. When the skill is invoked, the task is strategy construction, even if the user's wording looks like a clinical, prevalence, treatment, prognosis, or background question. Do not search PubMed or the web to answer the evidence question. First require a plain-language research/review question, then ask for optional seed PMIDs, then build and validate the Boolean strategy.

## Stage map and banner requirement

Use this numbered stage map as the canonical sequence. Each transition needs a user-facing stage report per `SKILL.md` at one of two levels: a `full banner required` at decision gates (naming the stage, the exact reference files in force, work being done now, work allowed now, work not being done yet, and any user/protocol decision needed), or a one-line `stage marker` (stage name plus governing reference files) elsewhere. Promote a `stage marker` to a full banner whenever a user/protocol decision arises.

Track build progress in the manifest rather than re-deriving it from the conversation each turn: record the current stage, gate decisions, and any open user question with `scripts/manifest_tool.py state` (see `references/mesh-and-pubmed-tools.md`), and run `state check-ready` before final handoff.

1. **Question intake**: plain-language research/review question. `full banner required` at the start of a new task. References: `SKILL.md`, `references/workflow.md`.
2. **Seed intake**: seed PMID decision. `full banner required` before asking for or accepting seed status. References: `SKILL.md`, `references/workflow.md`.
3. **Limited seed evidence**: limited seed fetch/mining, if supplied, only to inform concept analysis, including pre-gate seed triage and optional seed-set expansion via `related` for term discovery. `stage marker`. References: `references/workflow.md`, `references/concept-analysis-and-gating.md`, `references/seed-pmid-validation.md`.
4. **Concept gate**: formal concept analysis and concept gate. `full banner required` before the gate summary or gate question. References: `references/framework-selection.md`, `references/concept-analysis-and-gating.md`, `references/anti-patterns.md`.
5. **Pre-MeSH brainstorm**: pre-MeSH vocabulary/domain brainstorm for weak-MeSH or social-science concepts. `stage marker`. References: `references/concept-analysis-and-gating.md`, `references/tiab-expansion.md`.
6. **MeSH/PubMed exploration**: MeSH/PubMed exploration. `stage marker` before any MeSH lookup, ATM check, broad PubMed exploration, or sample-record work. References: `references/mesh-and-pubmed-tools.md`, `references/workflow.md`.
7. **Text-word expansion**: text-word, proximity, and wildcard candidate generation. `stage marker`. References: `references/tiab-expansion.md`, `references/wildcard-and-truncation.md`.
8. **Block testing**: concept-block construction and testing. `stage marker` before concept-block counts, pairwise counts, optional block tests, filter checks, or focused variant tests; promote to a full banner when an optional block, filter, or focused-variant decision arises. References: `references/workflow.md`, `references/concept-analysis-and-gating.md`, `references/mesh-and-pubmed-tools.md`, `references/bramer-reciprocal-gap-analysis.md`.
9. **Validation**: seed PMID validation, if seeds were provided, plus optional relative-recall estimation against a benchmark set. On a **no-seed build**, offer the optional heuristic recall check here (full banner, `User decision needed`); see `references/no-seed-recall-estimation.md`. `stage marker` before known-item validation, relative-recall estimation, or variant validation; promote to a full banner when the no-seed recall offer is made. References: `references/seed-pmid-validation.md`, `references/no-seed-recall-estimation.md`, `references/workflow.md`.
10. **Revision**: revision. `stage marker`. References: `references/workflow.md`.
11. **Final QA**: final query hygiene and QA. `stage marker` before final parse checks, hygiene reruns, or `final-qa`. References: `references/workflow.md`, `references/mesh-and-pubmed-tools.md`.
12. **Audit output**: save audit Markdown file with decision ledger, then save the canonical `run_manifest.json` recording every command, output path, date, count, and superseded file. `stage marker` before rendering or saving the audit file. References: `references/audit-template.md`, `references/prisma-s-reporting.md`.
13. **Peer-review handoff**: documented draft strategy for human PRESS peer review. References: `references/audit-template.md`, `references/prisma-s-reporting.md`.

High-sensitivity PubMed strategies use this mental model:

```text
(MeSH layer OR title/abstract layer OR proximity/wildcard layer)
AND
(MeSH layer OR title/abstract layer OR proximity/wildcard layer)
```

MeSH does not replace free text. Free text does not replace MeSH. Proximity and wildcards do not replace either.

## 1. Understand the review question

Before extracting candidate slots, read `framework-selection.md` and choose the appropriate framework. The default LLM behaviour is to force every question into PICO; this often reduces recall when the question is exposure-based (PECO), qualitative (PICo/SPIDER), diagnostic (PIRD), or scoping (PCC). State the framework choice and reason in the concept-analysis ledger before extracting slots.

Before asking for seed PMIDs, confirm that the user supplied an independently stated plain-language topic, review question, or protocol-style question. Pasted Boolean syntax, line sets, field-tagged queries, and strategy fragments are not accepted as build input; `SKILL.md` "Required Input" is canonical for handling them (ask only for the plain-language question and stop, or, if syntax appears alongside prose, restate or confirm the question before seed intake).

Identify:

- population or problem
- intervention, exposure, phenomenon, or condition
- comparator, if essential
- outcome, if essential
- study type, if explicitly required
- setting, date, language, publication type, or other limits, if explicitly required

Do not assume every PICO element belongs in the search.

For high sensitivity, outcomes and comparators are often omitted unless central to the topic.

## 2. Ask once for seed PMIDs

Before asking for seed status, emit the **Seed intake** stage banner (references in force and blocked actions per the stage map above).

Ask the user once whether they have known relevant seed PMIDs. Make clear that seeds are optional. If the user has already provided seeds, do not ask again. This is the first action after the plain-language research/review question is confirmed; do not run PubMed answer searches first.

Pause and wait for the user's answer before running MeSH/PubMed exploration, drafting the strategy, searching PubMed for substantive answers, or asking the concept-gate question. Continue only after the user supplies seed PMIDs, says they have no seeds, or explicitly asks to proceed without seeds.

If the user supplies no seeds or asks to proceed without seeds, treat seed status as resolved and continue under the no-seed workflow; record the seed gate as `none` (`manifest_tool.py state resolve-gate seed none`) so the build is auto-detected as no-seed. State that true seed-derived MeSH, seed-derived text words, and known-item recall will be `not available - no seed PMIDs supplied`. Add that an **optional heuristic recall check** is available and will be offered at the Validation stage once a draft strategy exists; do not ask about it now (it cannot run before a draft and concept blocks exist). See `references/no-seed-recall-estimation.md`. When seeds are supplied, record the seed gate as `provided` (or `partial` when only some PMIDs are usable).

If seed PMIDs are supplied, normalize and deduplicate numeric PMIDs before limited pre-gate seed fetch/mining. Record malformed entries separately and do not pass them to PubMed. If fetch/mining reports missing or not-found PMIDs, document them, exclude them from seed evidence and later known-item validation unless corrected, and continue with any found records.

If no usable seed records remain after malformed and not-found PMIDs are excluded, proceed under the no-seed validation limits unless the user supplied corrected PMIDs. If valid found records remain, limited fetch/mining of those PMIDs is allowed after the seed decision and before the concept gate solely to inform the concept-analysis ledger. Optional seed-set expansion via `pubmed_tool.py related` (PubMed similar-articles and citation chaining) is also allowed here for term discovery; treat the expanded set as a candidate relevant set, label it separately from user-confirmed seed evidence, and do not treat neighbor retrieval as validated sensitivity. See `references/seed-pmid-validation.md`.

Pause before the concept gate only when a fetched seed is retracted or appears materially out of scope. Ask only whether to exclude the PMID, replace it, or retain it as a special validation seed, then stop until the user answers. Likely out of scope means the fetched title, abstract, or publication type clearly conflicts with the stated review question; ordinary uncertainty is recorded, not treated as a blocker.

Do not use seed triage as permission for broader PubMed exploration, block testing, validation, variants, final QA, or filter checks.

## 3. Run formal concept analysis and the concept gate

Before running the gate or asking the gate question, emit the **Concept gate** stage banner (references in force per the stage map above).

Use `concept-analysis-and-gating.md` as the canonical procedure for the detailed ledger, seed/no-seed branches, role definitions, sensitivity-dangerous concept handling, and concept-gate pilot-test protocol. Use `anti-patterns.md` to guard against catalogued failure modes (PICO-as-template, default outcomes/comparators, overfitting to seeds, ignoring failed seed retrieval, silent committal on ambiguous questions, one-shot Boolean). Use `goal-tracking.md` for `/goal` pre-creation rules and active-goal behavior.

Run this step after the seed PMID decision is resolved and, when seed PMIDs were supplied, after limited seed fetch/mining for concept evidence. Run it before MeSH lookup, broad PubMed exploration, or concept-block drafting. The goal is to decide which concepts become essential `AND` blocks, which remain inside existing `OR` blocks, which are omitted for sensitivity, and which require a methodological/filter decision.

Pause before MeSH lookup or concept-block construction whenever a candidate concept could become a materially plausible sensitivity-dangerous `AND` block or filter. Ask by default at the concept gate when such an optional block, focused variant, or filter is in play unless the protocol already fixes the decision. For `/goal`, do not call `create_goal` while seed status, concept-gate decisions, or required filter/limit decisions are unresolved; ask only the next unresolved decision.

Prefer fewer `AND` blocks.

Use:

```text
(concept 1)
AND
(concept 2)
```

or:

```text
(concept 1)
AND
(concept 2)
AND
(concept 3)
```

Avoid:

```text
(population)
AND
(intervention)
AND
(comparator)
AND
(outcome)
AND
(study design)
```

unless each block is truly essential.

## 4. Run the pre-MeSH vocabulary/domain brainstorm

Before MeSH lookup, run a lightweight vocabulary brainstorm for any social-science, psychosocial, behavioral, qualitative, health-services, or weak-controlled-vocabulary concept. For straightforward biomedical concepts with stable MeSH and terminology, this may be brief and documented as not needed.

Use `tiab-expansion.md` for the social-science/psychosocial checklist. Include author-language, disciplinary synonyms, adjacent theories, lived-experience terms, access/help-seeking terms, identity/minority-stress terms, disclosure/concealment terms, and unmet/perceived-need terms when relevant.

Ask one concise user-facing domain-framing question before MeSH lookup when vocabulary framing can materially change the strategy. Use wording like:

```text
Before MeSH lookup, I see several possible vocabulary frames for this concept: [A], [B], [C]. Should the sensitive strategy include all as within-block synonyms, or should any be treated as separate optional/focused concepts?
```

Do not ask about ordinary synonyms that clearly stay inside an existing `OR` block. Do not turn brainstormed adjacent constructs into extra `AND` blocks unless the user or protocol confirms they are essential.

Record accepted, rejected, and deferred brainstormed vocabulary families for the final audit.

## 5. Build each concept block

Before any MeSH lookup, ATM check, broad PubMed exploration, or sample-record work, emit the **MeSH/PubMed exploration** stage marker (references per the stage map above). Do not begin block testing, optional secondary block tests, filter checks, focused variants, final QA, or audit output unless already authorized by the concept gate.

Before selecting MeSH headings, run the pre-MeSH brainstorm where required, then run an aggressive MeSH sweep. Do not rely on a single descriptor lookup. Use `mesh-and-pubmed-tools.md` for the bundled `mesh_tool.py` and `pubmed_tool.py` commands referenced in this workflow.

Register the essential blocks for coverage tracking once the concept gate fixes them (`manifest_tool.py state register-blocks --blocks-file blocks.json`), and tag each MeSH sweep and block count with `--block <label>` when recording it in the manifest, so the per-block coverage gate can confirm every essential concept was actually swept and count-tested rather than skipped. Record a reasoned waiver for any requirement that genuinely does not apply (e.g. a concept with no MeSH descriptor). See *Per-block evidence coverage* in `mesh-and-pubmed-tools.md`.

For each essential concept:

1. Create a variant list from the user phrase, pre-MeSH brainstormed vocabulary, synonyms, acronyms, spelling variants, hyphenation variants, older/newer terminology, seed-paper title/abstract terms, seed-paper MeSH headings, and PubMed ATM/query translation clues. When seed PMIDs or a pilot relevant set exist, run `pubmed_tool.py term-rank` to rank candidate `[tiab]` and MeSH terms by enrichment (coverage and lift) against PubMed background and prioritise high-coverage, high-lift candidates over raw frequency; see `tiab-expansion.md`. When no seeds were supplied, you can still reach `term-rank` here by building a small, high-precision pilot relevant-set query and passing it via `--relevant-query-file` (favor precision, treat results as candidates not recall); this is post-gate block-building work, never pre-gate exploration.
2. Run `mesh_tool.py sweep --concept "..." --variant "..." --details --output <path> --pending-output <pending_variants.txt>`. For long variant lists, pass `--output` (full JSON written and checkpointed to the file, compact summary on stdout), `--pending-output` (rerunnable pending labels), and rely on the `--max-seconds` budget. If the result is `status: "partial"` (time budget or request errors), the MeSH layer is incomplete: rerun the listed `pending`/failed labels (a separate sweep is fine) and merge candidates before drafting the block, so recall is not silently reduced.
3. After each MeSH sweep, do not draft the concept block yet. Complete a MeSH candidate ledger first:
  - List sweep inputs separately from sweep outputs.
  - Add candidates from MeSH sweep output, seed-assigned MeSH, PubMed ATM/query translations, and sample-record indexing.
  - For each plausible descriptor or supplementary concept record (SCR), inspect descriptor details, scope, entry terms, related descriptors, and tree/explosion context where relevant.
  - Run `mesh_tool.py tree --descriptor ...` for every included descriptor and for every plausible rejected descriptor where scope, sibling context, descendants, SCR mapping, or explosion/noexp could affect the decision.
  - Accept, reject, or defer each candidate with a reason.
  - Harvest all non-ambiguous entry terms from accepted descriptors/SCRs as `[tiab]` candidates; document omitted entry terms.
  - Run separate sweeps for important subtypes, procedures, devices, drugs, acronyms, older terms, and newer terms, or state why they were not needed.
  - Test accepted descriptors in PubMed; test plausible rejected descriptors when the decision affects recall or noise.
  - Test MeSH-only, text-word-only, and combined concept-block counts.
  - Use `bramer-reciprocal-gap-analysis.md` for conditional reciprocal gap analysis when layer complementarity or term discovery needs deeper checking; otherwise record a reasoned waiver when the check is not needed.
  - Resolve or document all MeSH/SCR mappings surfaced by PubMed ATM before finalising the block.
4. Draft the concept block only after the candidate ledger is complete.

Each block should usually include:

- MeSH heading
- narrower MeSH headings, where useful
- MeSH entry terms as `[tiab]`
- seed-paper title and abstract terms
- synonyms
- acronyms
- singular and plural forms
- spelling variants
- hyphenation variants
- older and newer terminology
- proximity expressions (`"word1 word2"[tiab:~N]`) where word order varies
- wildcard stems where useful

Use `wildcard-and-truncation.md` before accepting proximity expressions or wildcard stems, especially when a stem may be short, ambiguous, or likely to retrieve unrelated concepts.

Run a proximity review pass for phrase-like concepts before finalising the text-word layer. Review is required when a concept uses multiple exact phrase variants with shared content words, phrase wording/order varies, PubMed reports a quoted phrase as absent from the phrase index, or loose same-field `[tiab] AND [tiab]` wording is used inside one concept block. Compare exact phrase(s), Boolean `AND`, and PubMed proximity variants, usually `~0`, `~1`, `~2`, and `~3`; use `~0` as PubMed's fallback for quoted phrases not found in the phrase index. Retain proximity only when testing supports it, otherwise record the rejected or not-applicable rationale.

Run a morphology pass for quoted `[tiab]` phrase families before finalising the text-word layer. Identify explicit singular/plural phrase pairs, generate phrase-final, phrase-anchored or concept-specific wildcard candidates when the morphology is predictable, test candidates with `pubmed_tool.py batch` or `search` when they may affect recall, and record the decision as `wildcard retained`, `explicit forms retained`, or `wildcard not applicable` in the title/abstract expansion log. Generic one-token wildcard stems require explicit testing/rationale before retention.

Pattern:

```text
(
  "Preferred MeSH Term"[Mesh]
  OR "Narrower MeSH Term"[Mesh]
  OR "entry term phrase"[tiab]
  OR synonym[tiab]
  OR acronym[tiab]
  OR "phrase variant"[tiab]
  OR "word1 word2"[tiab:~3]
  OR truncat*[tiab]
)
```

If a methodological filter is needed (study design, evidence type, age group, etc.), do not build an ad hoc block first. Use `validated-methodological-filters-and-hedges.md` to choose a validated, PubMed-appropriate filter where available. Common source families include Cochrane HSSS, McMaster HIRU Hedges, PubMed Clinical Queries, and the ISSG Search Filters Resource. Cite the source, version, interface, and any adaptation.

## 6. Decide whether a methodological filter or hedge is needed

Only add a methodological filter when the protocol or user genuinely requires a study design, evidence type, age group, species group, or other filter.

If a filter is needed:

1. Identify the filter purpose.
2. Choose a validated PubMed filter where available.
3. Prefer sensitivity-maximising versions for evidence synthesis.
4. Avoid copying Ovid, Embase, or CINAHL syntax into PubMed.
5. Record the source, version, interface, and any adaptation.
6. Plan to test both the topic-only strategy and the topic-plus-filter strategy.

If no filter is needed, state that no methodological filter was applied and why.

See `validated-methodological-filters-and-hedges.md`.

## 7. Test iteratively

Before concept-block counts, pairwise counts, full-strategy counts, optional secondary block checks, filter checks, or focused variant checks, emit the **Block testing** stage marker (references per the stage map above). If an optional secondary `AND` block, filter, or focused variant was not already authorized by the user or protocol at the concept gate, ask before testing it and stop. If counts, seed behavior, or noise patterns later reveal a meaningful optional-block or filter trade-off that was not obvious earlier, pause and ask before testing or promoting that focused/filter variant. Do not re-ask when the user already answered unless the observed evidence materially changes the decision context.

Use `mesh-and-pubmed-tools.md` for PubMed count, sample, batch, validation, and variant commands used during iterative testing. Use `bramer-reciprocal-gap-analysis.md` when a diagnostic controlled-vocabulary/text-word gap check is triggered or waived.

Test:

1. each accepted MeSH term
2. each plausible but rejected MeSH term
3. each major text-word cluster
4. each proximity review candidate, including exact phrase and Boolean `AND` comparisons, multiple `N` values where useful, concept-block with/without comparisons, rejected/not-applicable rationale, and seed PMID impact when seeds exist
5. each wildcard stem that may affect recall
5a. each phrase-final wildcard candidate from the morphology pass when explicit quoted `[tiab]` singular/plural pairs may affect recall
6. each concept block
6a. Bramer reciprocal gap analysis for concept blocks where layer complementarity or term discovery needs deeper checking; diagnostic `NOT` queries must be recorded as temporary checks, not final-strategy exclusions
7. each pair of blocks
8. the full topic-only strategy
9. the full topic-plus-filter strategy, if a filter is used
10. the strategy against seed PMIDs, if provided
11. whether adding the filter causes seed PMIDs to be lost
12. labelled search design alternatives with `pubmed_tool.py variants` when sensitivity/precision or workload trade-offs matter
13. relative recall against a benchmark relevant set with `pubmed_tool.py recall` when an objective sensitivity check beyond known-item seeds is warranted, passing the concept blocks via `--blocks-file` to find the bottleneck block. On a **no-seed build**, this is the optional heuristic check: offer it once (full banner), and if accepted build the benchmark by pilot query → `related` expansion → `recall`, then record the outcome with `manifest_tool.py state resolve-recall-offer <done|declined|not-applicable>`. See `references/no-seed-recall-estimation.md`.

If an accepted no-seed recall check shows overall heuristic recall below `70%`, any essential block below `60%`, or a clear bottleneck block with plausibly in-scope misses, revise that block or document why each miss is out of scope. Do not proceed to audit output until the revised query is retested.

When seed PMIDs were provided, use `seed-pmid-validation.md` for known-item validation, missed-seed diagnosis, topic-only versus topic-plus-filter seed retrieval checks, and optional relative-recall estimation. Relative recall is relative to the benchmark, not absolute sensitivity; against a seed-expansion benchmark it is a heuristic.

## 7a. Record search design alternatives

Do not test a focused, precision, filter, or reserve variant that adds an optional secondary `AND` block, limit, or filter unless the protocol already requires it or the user has explicitly authorized testing it.

When broad terms, optional blocks, proximity distance, wildcards, or filters create a meaningful sensitivity/workload trade-off, create a search design ledger with labelled alternatives:

- `sensitive` or `main`: recall-first baseline
- `focused`: removes or narrows noisy terms while preserving essential concepts
- `precision`: intentionally workload-reducing design
- `filter`: topic-plus-methodological-filter design
- `reserve`: plausible fallback not selected

For each design, record the hypothesis, changes from baseline, recall risk, workload rationale, decision status, and decision reason. Use `pubmed_tool.py variants --seed-pmids ...` to attach known-item retrieval when seeds exist. Use `--labelled-samples labelled_samples.json` only when a PMID-level relevance-labelled pilot sample exists. NNR equals labelled sample size divided by relevant labelled records; without labels, report counts as workload proxies, not precision.

Select the sensitive design by default. Prefer a focused design only when it preserves all in-scope seed PMIDs, keeps MeSH plus text-word coverage for each essential concept, materially reduces count or estimated NNR, avoids parse/translation hazards, and documents every removed or narrowed term, filter, or block.

## 7b. Maintain and write the final audit Markdown ledger

Before rendering or saving the audit Markdown file, emit the **Audit output** stage marker (references per the stage map above). Include the stage trace when stage notes were recorded.

Final output uses the template in `audit-template.md`. Use `prisma-s-reporting.md` for PRISMA-S reporting notes and evidence-synthesis reporting caveats. While searching, keep enough notes to populate that report without reconstructing unsupported details later.

For every completed strategy build, create a Markdown audit file in the user's working/output folder, preferably `audit_YYYY-MM-DD.md` or `audit_<topic-slug>_YYYY-MM-DD.md`. The file must contain the final strategy audit report and a decision ledger. If a matching audit file already exists, do not overwrite it silently; use a clear suffix or ask when overwriting is ambiguous. Report the saved audit Markdown path in the final response. If a structured audit JSON artifact was created, also report that JSON path in the final response and Reporting notes. The optional `.xlsx` audit workbook is a supplement, not a replacement for the Markdown audit file.

When possible, collect the audit facts into a structured JSON object, save that object to a UTF-8 audit JSON file such as `audit_<topic-slug>_YYYY-MM-DD.json`, and render the report from that file with `scripts/audit_markdown.py`. The tool writes the full Markdown report to disk and prints only a compact JSON receipt by default, which keeps token use low during long strategy builds. Use `--if-exists suffix` when an automatic clear suffix is preferred over failing on an existing file. When completing an `audit-scaffold` file, save authored decisions as a small overlay JSON and render with `--overlay-json <decisions.json>` so mechanical scaffold fields stay intact. Avoid large shell pipelines such as PowerShell `ConvertTo-Json | python scripts/audit_markdown.py -`; for completed strategy builds, file-based JSON input is the reliable path.

Whenever a final PubMed search strategy is generated or presented before the audit Markdown exists, explicitly offer to generate the complete Markdown audit file. For completed builds, proceed to audit output and save the Markdown by default; do not make the audit optional at final handoff. If the user asked only for the strategy or pauses before audit output, ask one concise question offering the complete audit Markdown that documents every workflow stage, user/protocol decision, search-design decision, evidence file reviewed, and rationale. Do not claim the audit file exists until it has been rendered and saved.

Keep a canonical `run_manifest.json` alongside the audit files using `scripts/manifest_tool.py`. As material commands run and as files are written, append entries with `manifest_tool.py add` so the manifest records every command, its output path, the date, the result count, and any superseded file; when an audit or query file is re-rendered with a clear suffix instead of being overwritten, record the old path as superseded by the new one. Before finishing, run `manifest_tool.py show --validate --check-files --require-ready`; `--require-ready` is the binding handoff gate and exits non-zero unless the build-state concept gate is resolved and no user question is pending. Resolve any reported issue, then report the saved `run_manifest.json` path in the final response and Reporting notes. See `references/mesh-and-pubmed-tools.md`.

No reviewed JSON, no decision. If a decision depends on relevance, scope, noise, seed validity, term discovery, or concept role, the audit must identify the saved JSON file reviewed. Receipt-only stdout from `fetch`, `mine`, or `sample` cannot support the decision.

Record:

- decision ledger: each user/protocol or search-design decision point, options considered, evidence or test used, decision made, rationale or recall-risk note, and where the decision is reflected in the strategy/report
- search structure: essential blocks, within-block terms, concept-gate status, dangerous optional blocks, user decisions, filters, and omitted concepts
- MeSH work per concept: candidate ledger inputs and outputs, candidate sources, `tree` outputs or unusual SPARQL follow-ups where actually checked, accepted/rejected/deferred descriptors or SCRs with rationale, entry terms harvested and omitted, ATM/SCR mapping decisions, and MeSH-only/text-word-only/combined block counts
- seed or sample record evidence: seed-derived MeSH only when seed PMIDs were supplied; otherwise label any fetched-record MeSH as sample-record patterns. When the seed set was expanded with `related`, record the expansion provenance (link types used, per-link counts, caps, high-overlap candidate PMIDs) and keep related-set evidence labelled separately from user-confirmed seed-derived evidence
- pre-MeSH brainstorm evidence: vocabulary families considered, domain-framing question and answer when asked, and accepted/rejected/deferred brainstorm terms
- PubMed query translation observations: free-text exploratory queries, ATM mappings, parse warnings, and whether any mapping was added explicitly
- PubMed count checks: MeSH-only, text-word-only, combined concept blocks, Bramer reciprocal gap counts/samples when performed, pairwise blocks when useful, final topic-only strategy, topic-plus-filter strategy, focused/reserve variants, low-count plausibility hook when final topic-only count is `<500` (see `references/low-count-plausibility.md`), and differential/noise samples when run
- title/abstract expansion decisions: MeSH-entry-derived terms, seed-derived terms, sample-record-derived terms, acronyms added or rejected, singular/plural forms, spelling and hyphenation variants, proximity expressions added or rejected, and wildcard stems added or rejected
- sample inspection notes: number inspected, sampling method or sort, observed relevance/noise patterns, and whether records were formally labelled
- relative-recall estimation: benchmark source (independent gold standard vs. seed-expansion heuristic), benchmark size, relative recall, per-block recall and bottleneck block, missed-record inspection outcome, revision decision, final retest result, and `not performed` when no benchmark recall check was run; keep distinct from known-item seed validation
- QA and reporting notes: final query hygiene, `query_translation_drift`, `final-qa`, `filter-check`, limits/restrictions, audit workbook path, and remaining caveats
- run manifest: confirm `run_manifest.json` records each material command, output path, date, count, and superseded file, and report its saved path

Guardrails:

- If an item was not tested, say `not performed`.
- If a data source cannot support an item, say `not available`.
- If an item does not apply to the topic, say `not applicable`.
- Do not report true seed-derived MeSH, known-item recall, formal precision, or NNR unless the necessary seed PMIDs or labelled samples were provided and tested.
- Report relative recall only as relative to its benchmark, never as absolute search sensitivity; flag a seed-expansion benchmark as a heuristic and name the benchmark source.
- Do not report exact top-page relevance counts unless those records were actually inspected and labelled during the run.
- Do not present comprehensive MeSH tree positions unless `tree`, unusual SPARQL follow-up checks, or equivalent tree evidence were actually run; `details` alone is not comprehensive tree review.
- Do not reconstruct command history that was not recorded. Summarize tool work performed from available outputs.
- Do not imply PRESS peer review, non-PubMed database translations, or grey-literature coverage unless they were actually performed.

## 8. Revise

Revise when:

- a seed PMID is missed
- an in-scope gold-standard PMID is missed
- late-arriving gold-standard PMIDs are supplied after validation; reopen validation/revision and classify each one before final handoff
- a no-seed heuristic recall check shows overall recall below `70%`, any essential block below `60%`, or a bottleneck block with plausibly in-scope misses
- a term retrieves mostly unrelated concepts
- a MeSH heading is too broad or too narrow
- a concept block is over-constrained
- the final topic-only strategy retrieves `<500` records and low-count diagnosis suggests avoidable narrowing or a bottleneck block
- a phrase is too exact
- a wildcard stem is too short or too noisy
- a recent record lacks MeSH indexing and needs text-word coverage
- an in-scope seed PMID is lost after adding a methodological filter

When a recall check identifies a bottleneck block, revise that block or document why each miss is out of scope. Do not proceed to audit output until the revised query is retested. If a missed seed or gold-standard PMID appears out of scope, document the scope reason and keep it out of the strategy rather than overfitting the query.

## 9. Final query hygiene

Before final parse checks, hygiene reruns, or `final-qa`, emit the **Final QA** stage marker (references per the stage map above).

Before presenting the final draft:

1. Save the final topic-only strategy, and topic-plus-filter strategy if applicable, as UTF-8 query files.
2. Deduplicate exact repeated terms inside `OR` blocks while retaining intentional spelling, plural, hyphenation, field-tag, and proximity variants. `hooks_tool.py final-qa` reports exact duplicates as `duplicate_term`; removing them is recall-neutral and also clears repeated `not found in PubMed` notices caused by a duplicated zero-hit term.
3. Run `pubmed_tool.py search --query-file ... --retmax 0`.
3a. If the final **topic-only** strategy retrieves `<500` records, read `references/low-count-plausibility.md` and run `hooks_tool.py low-count-review` before handoff. Diagnose whether the count is expected or caused by avoidable narrowing. Do not expand automatically just to exceed 500 records. Record the hook output in the manifest and include `manifest_tool.py show --require-low-count-review` in the final handoff check.
4. Review PubMed parse/translation warnings, especially `phrases_not_found` (zero-hit terms), `fields_not_found` (unrecognized field tags), `quotedphrasesnotfound`, `phrasesignored`, output messages, and other `query_translation_drift` issues.
5. Remove, replace, or justify dead quoted phrases and other warnings, then rerun until warnings are resolved or documented.
5a. For each zero-hit term reported by `phrases_not_found` or `quotedphrasesnotfound`, first check spelling, hyphenation, and spacing variants in case it is a typo for a real term rather than genuinely absent; fix typos instead of removing them. For genuinely zero-hit terms, the default is to **remove and document** them as removed zero-hit terms, because they match no records and removal is recall-neutral in the current index; offer the user the option to keep any **free-text** zero-hit term as an intentional zero-hit term for future-proofing, and promote this stage to a full banner with `User decision needed` while the choice is open. A zero-hit term carrying a controlled-vocabulary field tag (`[Mesh]`, `[Mesh:noexp]`, `[Majr]`, `[Supplementary Concept]`, or the `[mh]`/`[majr]` equivalents) is **never** a valid future-proofing keep — a real MeSH descriptor always exists in the index, so a zero-hit controlled-vocabulary term indicates a misspelled or nonexistent heading: fix the typo or remove it, and never retain it as an intentional zero-hit term. Record each removed and each kept zero-hit term, with reasons, in the audit decision ledger and PRISMA-S notes.
6. If variants were tested, rerun the selected final variant after hygiene so the reported count matches the delivered strategy.
7. Run `hooks_tool.py final-qa --strategy-file ...` after the final query text stabilizes.
8. Treat `proximity_review_needed` findings as documentation warnings: compare exact phrases, Boolean `AND`, and proximity widths, retain proximity only when testing supports it, or document why proximity was rejected or not applicable.
9. Treat `singular_plural_wildcard_review` findings as documentation warnings: test the phrase-final, phrase-anchored/concept-specific wildcard candidate or document why explicit singular/plural forms were retained, then record the morphology-review decision in the audit.
10. Run the per-block coverage check (`manifest_tool.py state coverage`, or `show --require-coverage` alongside `--require-ready`). Resolve any `coverage gap` by recording the missing MeSH sweep / block count against the block, or a reasoned waiver, before handoff. See *Per-block evidence coverage* in `mesh-and-pubmed-tools.md`.

### Final validation and cleanup offer

This is a required closing gate for every completed strategy build. Do not silently resolve issues and move on: consolidate the findings from the final `pubmed_tool.py search --query-file ... --retmax 0` run (its `query_translation_drift` hook) and `hooks_tool.py final-qa` into one short, user-facing report, grouped by the action each finding needs:

- **Errors to fix:** unbalanced parentheses/quotes, truncation inside a proximity expression, and `fields_not_found` (an unrecognized field tag). These break or mis-scope the search and must be fixed.
- **Duplicate terms (`duplicate_term`):** remove by default. An exact repeated atom is logically redundant (`(A OR A)` is identical to `(A)`), so removal is recall-neutral and nobody benefits from keeping a literal duplicate; it also clears repeated `not found in PubMed` notices from a duplicated zero-hit term. Surface it in the report rather than stripping silently for two reasons: you must drop the *redundant-context* copy (e.g. the one nested inside a narrower `MeSH AND (...)` sub-clause) and never the broad standalone copy, which would narrow retrieval; and the duplication usually signals a wider redundancy worth reviewing.
- **Zero-hit terms (`phrases_not_found` / `quotedphrasesnotfound`):** **remove + document** by default, because they match no records and removal is recall-neutral; offer the user the option to keep any as an intentional zero-hit term **(free-text terms only — a zero-hit `[Mesh]`/`[Majr]`/`[Mesh:noexp]`/`[Supplementary Concept]` term is a misspelled or nonexistent heading, so fix or remove it, never keep it)**. Check spelling/hyphenation/spacing variants first and fix typos rather than removing them (see step 5a).
- **Proximity review (`proximity_review_needed`):** compare exact phrase(s), Boolean `AND`, and proximity widths, usually `~0` to `~3`; retain proximity only when testing supports it, or record why proximity was rejected or not applicable. This is a review warning, not an automatic insertion instruction.
- **Singular/plural wildcard review (`singular_plural_wildcard_review`):** test the phrase-final, phrase-anchored/concept-specific wildcard candidate or document why explicit quoted `[tiab]` singular/plural phrase variants are safer. This is a morphology-review warning, not an automatic replacement instruction.
- **Recall-reducing warnings:** `[Majr]`, `NOT`, language/date/species/age/publication-type/full-text limits, and short wildcards. Flag each and either justify it against the protocol or remove it with the user. Diagnostic Bramer reciprocal gap queries may use `NOT` during block testing only when documented under `bramer-reciprocal-gap-analysis.md`; final-strategy `NOT` still requires separate protocol justification.
- **Low-count plausibility check:** when the final topic-only count is `<500`, follow `references/low-count-plausibility.md`: report the count, diagnostics, relaxed variant test or reason not applicable, final decision, and final count after revision if revised. Treat the count as a recall warning, not as proof of precision and not as an automatic expansion target.

Then ask once whether to apply the offered cleanups. Apply only the approved changes, re-save the query file, and re-run `search --query-file ... --retmax 0` to confirm the delivered count matches what you report. Promote this stage to a full banner with `User decision needed` whenever the report contains anything in an offer-only category.

Guardrail: this gate only removes terms that do not reduce recall — exact **duplicate terms** and genuinely **zero-hit terms** (which match no records) are removed and documented by default, and genuine **parse errors** are fixed. Anything that actually retrieves records — recall-reducing limits, narrow filters, `[Majr]`, `NOT`, short wildcards, or weak-but-nonzero terms — is **offer-only and default to keep**, and is never removed without the user's approval. A `not found` term is removed only after confirming it is not a typo for a real term. Record every removal and every kept term in the audit decision ledger and PRISMA-S notes.

Do not use hygiene to silently narrow a recall-first strategy.

## 10. Stop

Stop when:

- the concept gate is completed for completed strategy builds; use `not performed` or `not applicable` only for incomplete, abandoned, or non-build reporting contexts
- in-scope seed PMIDs and gold-standard PMIDs are retrieved; a final strategy cannot be handed off with missed in-scope seeds or gold-standard PMIDs
- any missed supplied PMID is classified as either missed because the query failed or not retrieved because the PMID appears out of scope, with the evidence and revision decision documented
- essential concepts have MeSH and text-word coverage after an aggressive MeSH sweep
- accepted and rejected plausible MeSH descriptors/supplementary concepts are documented
- important variants have been considered
- Bramer reciprocal gap analysis has been performed, waived with rationale, or marked `not applicable` for each concept where the check was considered
- any methodological filter has been chosen from a validated source where available
- the topic-only and topic-plus-filter versions have been compared when a filter is used
- final query hygiene has removed exact duplicates and dead PubMed phrases, or remaining warnings are documented, and the required final validation and cleanup offer has been presented with the user's include/exclude/remove decisions applied or recorded
- proximity review findings have been tested or documented as rejected/not applicable in the title/abstract expansion log
- if the final topic-only strategy retrieved `<500` records, the low-count plausibility hook was run and recorded; any needed expansion was retested and before/after counts were documented
- further expansion mainly adds unrelated noise
- if a final strategy was generated or presented before audit output, the complete Markdown audit file was generated for a completed build or explicitly offered when the user paused before audit output
- audit Markdown file with decision ledger has been saved and its path is reported
- the run manifest (`run_manifest.json`) has been saved and its path is reported, and `manifest_tool.py show --validate --check-files --require-ready` passes (concept gate resolved, no user question pending)
- per-block evidence coverage has been checked (`state coverage` / `show --require-coverage`): every essential block has a MeSH sweep and a block count recorded against it, or a reasoned waiver; any `coverage gap` is resolved or documented
- on a no-seed build, the optional heuristic recall check was offered and its outcome recorded (`state resolve-recall-offer <done|declined|not-applicable>`; `show --require-recall-offer` passes); see `references/no-seed-recall-estimation.md`
- any accepted no-seed heuristic recall check that crossed the low-recall gate was followed by missed-record inspection, block revision or out-of-scope documentation, and retesting
- caveats are documented
- the strategy is flagged as a draft pending human peer review (PRESS, McGowan et al., 2016)
