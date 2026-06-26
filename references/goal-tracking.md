# Goal Tracking

Use this reference only when the user explicitly starts with `/goal` or asks for goal tracking. Do not auto-start goals for routine PubMed tasks.

Treat `/goal` as a request for goal tracking, not as a requirement to call `create_goal` immediately. If required human decisions are pending, collect them one at a time before creating the active goal so the goal runner does not repeatedly resume while waiting for input.

## Goal states

Use these states for `/goal` PubMed work:

1. `goal_requested_intake_pending`: The user requested goal tracking, but required human decisions are unresolved. Do not call `create_goal`. Ask only the next unresolved required intake question: plain-language research/review question first, seed PMID decision second, then concept-gate/filter decisions.
2. `goal_active_autonomous`: Required upfront decisions are resolved. Call `create_goal` once and continue with MeSH/PubMed exploration, testing, validation, QA, and final delivery.
3. `goal_active_blocked`: An unexpected human-input blocker appears after goal creation. Ask once and stop. On later resumes before the user answers, do not call tools, do not restate the workflow, do not run a completion audit, and do not repeat the full checkpoint. Reply only: `Still paused for user input: [specific missing decision]. No further PubMed work can continue until that is answered.`
4. `goal_completion_audit`: Use only after the final strategy appears complete. Run the completion audit, then call `update_goal` only if no required work remains.

Before goal creation, require an independently stated plain-language research/review question or protocol-style question. Pasted Boolean syntax, line sets, field-tagged queries, and strategy fragments are not accepted as build input (see `SKILL.md` "Required Input"); ask only for the research/review question and stop. After the research question is confirmed, shallowly parse only enough to identify seed, concept-gate, and required filter/limit decisions. After seed status is resolved and seed PMIDs were supplied, limited seed fetch/mining is allowed before goal creation solely to inform concept-gate/filter decisions. Do not run MeSH lookup, broad PubMed searching, block testing, validation, variants, final QA, or filter checks until the required upfront decisions are resolved.

If a goal already exists, use it only when it clearly matches the current PubMed task. If it does not match, explain that a new active goal cannot be created in this thread and continue without claiming goal tracking.

## Pre-goal human decisions

For strategy-building tasks, resolve these before calling `create_goal`:

- plain-language research/review question
- seed PMID decision
- concept-gate decision for sensitivity-dangerous optional blocks or filters
- methodological filter or limit decisions when required by the request or protocol

Required intake sequence:

1. If the plain-language research/review question is missing or only represented by Boolean syntax, ask only for the research/review question and stop.
2. If seed PMID status is pending after the research question is confirmed, ask only whether the user has known relevant seed PMIDs and stop. Do not ask the concept-gate, filter/limit, or variant-selection question in the same response.
3. Only after the user supplies seed PMIDs, says they have no seeds, or explicitly asks to proceed without seeds, use limited supplied-seed evidence when available and ask the high-sensitivity concept-gate question for sensitivity-dangerous blocks or filters.
4. Treat methodological filter or limit decisions as part of the post-seed concept-gate/filter stage unless the protocol already resolves them.

After those decisions are resolved, call `create_goal` once for the remaining autonomous strategy-building work and continue with MeSH/PubMed exploration, testing, validation, QA, and final delivery.

Use wording like:

`Goal tracking requested. I am collecting the required upfront decisions before creating the active goal, so the goal runner does not repeatedly resume while waiting for input.`

If all required decisions are already supplied in the prompt, create the goal immediately.

## Active-goal blockers and completion

For unexpected blockers after goal creation, follow `goal_active_blocked`.

Do not use token budgets as a waiting workaround. A token budget is accounting, not a pause control.

When a PubMed task has an active goal, treat the goal as the long-running container for the autonomous build work after required upfront decisions are resolved. Continue the workflow across turns until the final documented strategy is delivered. Any unexpected human pause after goal creation is a blocker inside the goal, not a failure or completion point.

Suggested objective wording:

- Strategy-building task: `Build and validate a high-sensitivity PubMed strategy for [topic], using the resolved seed PMID, concept-gate, and filter decisions.`

Before goal creation, ask required human-decision questions normally and compactly, but keep the required sequence: research/review question first, seed PMID question second, then high-sensitivity concept-gate/filter questions only after the seed answer. After goal creation, give a compact checkpoint only for unexpected blockers: what has been decided, what input is needed, the recommended default, and the exact next workflow step after the user answers. If goal tooling is unavailable, use the normal pause/resume workflow and do not claim goal tracking.

Complete or mark an active goal complete only after the seed PMID decision is resolved, the concept gate is resolved when applicable, MeSH/PubMed testing is completed or explicitly marked not performed, seed validation is completed when seeds exist, final QA/filter checks are run when applicable, and the final draft strategy is delivered and flagged for human peer review.

## Pilot checks

Run these lightweight behavioral checks after goal-tracking documentation changes:

1. `/goal` with no plain-language research question: ask only for the research/review question; do not call `create_goal`; do not ask for seeds in the same response.
2. `/goal` with a confirmed research question and no seed status: ask only whether the user has known relevant seed PMIDs; do not call `create_goal`; do not bundle the concept-gate, filter, or variant-selection question.
3. `/goal` with seeds and a dangerous optional concept: do not ask for seeds again; treat seed status as resolved; limited seed fetch/mining may inform the concept-gate or filter decision before goal creation; call `create_goal` only after seed, concept-gate, and required filter/limit decisions are resolved.
