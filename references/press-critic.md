# PRESS-Informed Internal Critic

Use this reference after a complete draft has empirical probe results and before final handoff. Repeat it after every material revision.

## Status

This is an automated, PRESS-informed internal self-review. It does not constitute PRESS peer review, which requires an independent information specialist. Always retain the external human peer-review handoff.

## Independence

Run the critic in fresh context when possible. Give it the raw artifacts needed to review the draft, not the generator's intended answer or preferred fix:

- plain-language review question and protocol decisions;
- current versioned retrieval-scope artifact;
- candidate-screening ledger and discovery/holdout summary;
- current strategy and concept-block files;
- MeSH candidate ledger and title/abstract expansion log;
- PubMed translations, counts, samples, seed/holdout results, gap analyses, and filter comparisons;
- prior critic findings and revision dispositions only when checking whether they were resolved.

Freeze exactly those inputs before review:

```bash
python scripts/critic_tool.py --build-bundle --evidence strategy=strategy_v1.txt --evidence scope=retrieval_scope_v1.json --evidence ledger=candidate_ledger.json --evidence probes=probe_summary.json --output critic_evidence_1.json
```

The bundle hashes every file. A critic receipt fails if evidence changes after review.

## Required review domains

Review the six PRESS 2015 elements:

1. translation of the research question;
2. Boolean and proximity operators;
3. subject headings;
4. text-word searching;
5. spelling, syntax, and line numbers;
6. limits and filters.

Also review hybrid-workflow risks that PRESS self-mapping alone does not capture:

- objective evidence changed scope without a new scope version;
- unscreened records influenced term mining;
- the same records were used for discovery and presented as independent validation;
- an essential block is fragile, seed-losing, or dominated by brittle phrases;
- an optional eligibility element was promoted to a required `AND` block;
- a low count, filter, or noisy sample drove silent narrowing;
- a structural revision left block registration or validation stale.

## Finding schema

Save each round as `critic_round_<N>.json`:

```json
{
  "critic_version": 2,
  "round": 1,
  "scope_version": 1,
  "strategy_file": "strategy_v1.txt",
  "evidence_bundle": "critic_evidence_1.json",
  "reviewed_domains": [
    "research-question",
    "operators",
    "subject-headings",
    "text-words",
    "syntax",
    "limits-filters",
    "hybrid-integrity"
  ],
  "domain_verdicts": [
    {"domain": "research-question", "status": "pass", "evidence_refs": ["scope", "strategy"]}
  ],
  "overall_status": "revise",
  "findings": [
    {
      "finding_id": "F001",
      "press_element": "3. Subject headings",
      "severity": "must-fix",
      "classification": "lexical",
      "affected_component": "condition block",
      "evidence": "mesh_condition.json and block_counts.json",
      "evidence_refs": ["strategy", "probes"],
      "recommendation": "Inspect the broader descriptor and its tree context.",
      "required_reprobe": "MeSH-only, tiab-only, combined block, holdout retrieval",
      "status": "open"
    }
  ]
}
```

Allowed severities are `must-fix`, `should-fix`, and `document`. Allowed classifications are `lexical`, `structural`, `scope`, `filter`, `syntax`, and `reporting`. Allowed finding statuses are `open`, `resolved`, `accepted-risk`, and `not-applicable`.

Version 2 requires one evidence-referenced verdict for each required domain (the abbreviated example above shows one). `not-applicable` requires a rationale. Finding IDs are stable across rounds. Validate the artifact with `scripts/critic_tool.py`. `overall_status: pass` is invalid while an open actionable finding exists, and the manifest rejects a round that silently drops a previously open ID.

## Routing

- **Lexical:** revise only the affected descriptor or text-word `OR` layer; rerun its counts, samples, gap analysis when applicable, and validation.
- **Structural:** reopen the concept gate, rerun `AND`-block admission, issue a new retrieval-scope version, re-register blocks, and rerun all affected combinations.
- **Scope:** pause for a user/protocol decision; do not infer eligibility from retrieved records.
- **Filter:** compare topic-only with topic-plus-filter and diagnose lost validation records before adoption.
- **Syntax:** repair, rerun PubMed translation, and rerun final QA.
- **Reporting:** correct the audit without claiming an empirical change unless a search artifact changed.

Read-only diagnostic probes may run before the user chooses a final narrowing design. User authorization is required to adopt a scope change, recall-reducing block, filter, or limit—not to gather the comparison evidence.

## Loop and pass criteria

For each round:

1. Validate and record the critic artifact in the manifest.
2. Route every finding and record its disposition.
3. Save a new strategy or scope version for material changes; never overwrite silently.
4. Rerun every required probe named by the finding.
5. Run a new critic round against the revised artifacts.

The internal critic passes only when:

- no `must-fix` finding is open;
- every structural change has a matching scope version and refreshed block registration;
- candidate-screening integrity is resolved;
- required re-probes and validation were rerun;
- unresolved `should-fix` findings are either resolved or explicitly accepted with rationale;
- remaining `document` findings appear in the audit and peer-review attention points.

Record each round, finding, change, before/after evidence, and disposition in the audit iteration ledger. Then hand the draft to an independent information specialist for actual PRESS peer review.
