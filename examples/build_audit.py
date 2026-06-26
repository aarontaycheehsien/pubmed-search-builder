"""Assemble structured audit notes for the robopets / care-home strategy
and dump to a UTF-8 JSON file for scripts/audit_markdown.py."""
import json

FINAL_STRATEGY = open('full_strategy.txt', encoding='utf-8').read().strip()

audit = {
    "title": "PubMed high-sensitivity search audit: robopets and the health and well-being of care-home residents",
    "topic": "robopets-care-homes",
    "review_question": ("What is the impact of robotic pets (companion / social robots) on the health and "
                        "well-being of residents in care homes / nursing homes / long-term care facilities?"),
    "date_searched": "2026-05-29",
    "result_count": 369,
    "topic_plus_filter_count": "not applicable",
    "focused_variant_count": "not performed",
    "main_variant_chosen": "Sensitive/main (robopets AND care-home setting), 369 records; retrieves all 3 in-scope seeds.",
    "final_strategy": FINAL_STRATEGY,
    "seed_status": "Yes - 3 in-scope seeds provided (29282989, 29165558, 29563027); 1 dropped as a typo (5181659).",
    "seed_pmids": ["29282989", "29165558", "29563027"],
    "limit_decisions": "None applied (no study-design, date, language, age, species, or publication-type limits). filter-check detected no filter intent.",

    "search_structure": {
        "concept_gate_status": "completed",
        "and_block_admission_summary": ("Two essential AND blocks (intervention AND setting). Outcome (health and well-being) "
                                        "and population sub-type (dementia / older adults) deliberately omitted to preserve recall, per user decisions."),
        "concepts_inside_or_blocks": ("Companion / social / socially-assistive robot synonyms and named devices (PARO, AIBO, Pleo) kept inside the "
                                      "intervention OR block; Skilled Nursing Facilities and Intermediate Care Facilities covered via Nursing Homes[Mesh] explosion."),
        "omitted_or_reserve_concepts": ("Health and well-being outcome block (omitted - user choice, sensitivity); dementia / older-adult population "
                                        "restriction (omitted - user choice, avoid overfitting to seeds); bare robot*[tiab] broadening (reserve, rejected - adds out-of-scope "
                                        "care / surgical robots); Residential Facilities[Mesh] exploded (rejected - adds Orphanages / Halfway Houses / Group Homes)."),
        "methodological_filters_or_limits": "None. No study-design, date, language, age, species, or publication-type limit applied.",
    },

    "concepts": [
        {
            "name": "Robopets / companion robots (intervention)",
            "scope": "robotic pets and companion / social robots used with residents; PARO, robotic seal / dog / cat, AIBO, Pleo",
            "coverage": "MeSH + tiab",
            "mesh_review": {
                "sweep_inputs": "robotic pet + variants: companion robot, social robot, socially assistive robot, robotic animal / seal / dog / cat, pet robot, therapeutic robot, PARO, AIBO",
                "sweep_outputs_and_candidate_sources": "MeSH sweep returned 35 candidates, almost all paro* / aibo* acronym noise; seed-assigned MeSH (Robotics, Pets, Play and Playthings, Animals). Only Robotics is relevant.",
                "details_tree_inspected": "Robotics D012371 tree: parents Artificial Intelligence / Electronics / Automation; descendants Robotic Surgical Procedures D065287, Autonomous Robots D000098402; entry terms Companion Robots, Social Robots, Socially Assistive Robots, Humanoid Robots, Telerobotics, Soft Robotics.",
                "candidates_accepted": "Robotics[Mesh] (exploded) - only relevant descriptor; broad, so specificity is carried by tiab; explosion harmless after AND with the care-home setting.",
                "candidates_rejected": "Pets[Mesh] and Play and Playthings[Mesh] (seed-assigned but denote real pets / real toys - far too broad and not robot-specific); paro* / aibo* descriptors (Paromomycin, Paroxetine, Parotid, Paroxysmal, etc. - acronym false matches).",
                "candidates_deferred_or_reserved": "Humanoid-robot terms and named humanoids (NAO, Pepper) - outside chosen scope; bare robot*[tiab] - reserve broadening, rejected on differential-sample evidence.",
                "scr_or_atm_mappings_resolved": "ATM maps PARO / AIBO / Pleo cleanly as Title/Abstract terms; NeCoRo and JustoCat returned 0 records and were removed.",
                "entry_terms_harvested_as_tiab": "companion robot*, social robot*, socially assistive robot* (from Robotics entry terms).",
                "entry_terms_omitted": "Humanoid Robots, Telerobotics, Soft Robotics, Remote Operations (Robotics) - off-topic for robopets.",
                "counts_tested": "MeSH-only 53,908; tiab-only 1,930; combined block 54,990.",
            },
        },
        {
            "name": "Care home / long-term-care setting (population + setting)",
            "scope": "nursing homes, residential aged care, long-term care, assisted living, homes for the aged, and their residents",
            "coverage": "MeSH + tiab",
            "mesh_review": {
                "sweep_inputs": "nursing home + variants: care home, long-term care, residential aged care, residential care, aged care facility, homes for the aged, assisted living, skilled nursing facility, residential facility, long-term care facility, old age home.",
                "sweep_outputs_and_candidate_sources": "MeSH sweep returned 8 candidates; seed-assigned MeSH (Long-Term Care, Nursing Homes); tree parent Residential Facilities D012112.",
                "details_tree_inspected": "Trees for Nursing Homes D009735 (children Skilled Nursing Facilities D012866, Intermediate Care Facilities D007380), Homes for the Aged D006707, Assisted Living Facilities D040561, Long-Term Care D008134, Nursing Home Residents D000099308; parent Residential Facilities D012112 (siblings Orphanages, Halfway Houses, Group Homes).",
                "candidates_accepted": "Nursing Homes[Mesh] (exploded to Skilled Nursing + Intermediate Care Facilities), Homes for the Aged[Mesh], Assisted Living Facilities[Mesh], Long-Term Care[Mesh], Nursing Home Residents[Mesh] (new 2026 descriptor).",
                "candidates_rejected": "Residential Facilities[Mesh] exploded (adds Orphanages / Halfway Houses / Group Homes - out of scope); Insurance, Long-Term Care (economics); Ambient Intelligence (smart-home tech, matched via 'ambient assisted living'); Home Nursing (care delivered at home, not institutional).",
                "candidates_deferred_or_reserved": "Residential Facilities[Mesh:noexp] - not used; generic residential care covered via tiab instead.",
                "scr_or_atm_mappings_resolved": "Long-Term Care[Mesh] translation confirmed; the hyphenated long-term care tiab phrase collapses to the same PubMed translation as the unhyphenated form, so the duplicate was removed.",
                "entry_terms_harvested_as_tiab": "old age home*, residential aged care (via aged care), homes for the aged, skilled nursing, nursing facilit*.",
                "entry_terms_omitted": "Senior Housing (too broad / US housing sense).",
                "counts_tested": "MeSH-only 78,298; tiab-only 88,784; combined block 120,728.",
            },
        },
    ],

    "user_decisions": [
        {"concept": "Health and well-being outcome block",
         "offered_because": "an outcome AND block would narrow recall and could drop records that do not use health / well-being wording in title or abstract",
         "decision": "omit", "handling": "Outcome judged at screening, not in the search."},
        {"concept": "Population restriction (dementia / older adults)",
         "offered_because": "all three on-target seeds are dementia residents, but the question concerns care-home residents generally",
         "decision": "no restriction - all care-home residents", "handling": "Setting block already captures residents; avoids overfitting to the dementia seeds."},
        {"concept": "Robopet breadth",
         "offered_because": "the boundary between pet / animal robots, companion / social robots, and all social / assistive robots materially changes scope",
         "decision": "robotic pets + companion / social robots (balanced)", "handling": "tiab phrases for companion / social / socially-assistive robots plus named devices; bare robot* excluded."},
        {"concept": "Seed PMID 5181659",
         "offered_because": "an off-topic 1967 cardiac-surgery paper, likely a mistyped PMID",
         "decision": "drop as typo", "handling": "Excluded from validation; the three PARO seeds were used."},
    ],

    "decision_ledger": [
        {"decision_point": "Seed PMID handling",
         "options_considered": "use all 4 / drop the off-topic one / request a correction",
         "evidence_or_test_used": "seed fetch + mine: 3 PARO long-term-care dementia studies in scope; 5181659 = 1967 myocardial-ischemia surgery, out of scope",
         "decision_made": "drop 5181659, keep 3 seeds",
         "rationale_or_recall_risk_note": "avoid distorting the strategy to retrieve an unrelated record",
         "reflected_in_strategy_or_report": "Seed PMID validation"},
        {"decision_point": "Concept gate",
         "options_considered": "intervention, setting, outcome (health/well-being), population sub-type (dementia/aged), comparator (plush toy), study design",
         "evidence_or_test_used": "concept-analysis ledger + seed evidence + user answers",
         "decision_made": "2 essential AND blocks (intervention AND setting); outcome, population, comparator, study design omitted",
         "rationale_or_recall_risk_note": "high sensitivity: only broad essential concepts become AND blocks",
         "reflected_in_strategy_or_report": "Search structure / final strategy"},
        {"decision_point": "Pre-MeSH vocabulary brainstorm",
         "options_considered": "pet/animal-form vs companion/social vs all-robot framing",
         "evidence_or_test_used": "brainstorm checklist + user breadth decision",
         "decision_made": "include pet/animal + companion/social-robot families; reject humanoid-only and bare robot*",
         "rationale_or_recall_risk_note": "honour chosen scope without drifting to all robots",
         "reflected_in_strategy_or_report": "tiab expansion log"},
        {"decision_point": "MeSH choice - intervention",
         "options_considered": "Robotics, Pets, Play and Playthings, Animals",
         "evidence_or_test_used": "sweep + tree D012371 + seed-assigned MeSH",
         "decision_made": "accept Robotics[Mesh] exploded; reject Pets / Play and Playthings",
         "rationale_or_recall_risk_note": "no robopet-specific MeSH exists; Pets/Playthings denote real pets/toys (too broad)",
         "reflected_in_strategy_or_report": "MeSH descriptors considered"},
        {"decision_point": "MeSH choice - setting",
         "options_considered": "Nursing Homes, Homes for the Aged, Assisted Living, Long-Term Care, Nursing Home Residents, Residential Facilities, Insurance LTC, Ambient Intelligence, Home Nursing",
         "evidence_or_test_used": "sweep + trees (D009735, D006707, D040561, D008134, D000099308, parent D012112)",
         "decision_made": "accept 5 specific descriptors (Nursing Homes exploded); reject Residential Facilities exploded, Insurance LTC, Ambient Intelligence, Home Nursing",
         "rationale_or_recall_risk_note": "explosion of Residential Facilities adds Orphanages/Halfway Houses/Group Homes; others are wrong sense",
         "reflected_in_strategy_or_report": "MeSH descriptors considered"},
        {"decision_point": "Text-word / wildcard choice",
         "options_considered": "specific robopet phrases, bare robot*, named devices, setting synonyms",
         "evidence_or_test_used": "batch counts + differential sample + final-qa",
         "decision_made": "keep phrase-anchored tiab + PARO/AIBO/Pleo; reject bare robot*; drop dead NeCoRo/JustoCat and the hyphen duplicate",
         "rationale_or_recall_risk_note": "balance recall against scope drift and parse noise",
         "reflected_in_strategy_or_report": "tiab expansion log / final strategy"},
        {"decision_point": "Sensitivity vs broadening variant",
         "options_considered": "sensitive main (369) vs robot*-broadened reserve (499)",
         "evidence_or_test_used": "FULL = 369 (3/3 seeds) vs FULL + robot* = 499; differential of ~130 sampled",
         "decision_made": "sensitive main (369)",
         "rationale_or_recall_risk_note": "broadening adds mostly out-of-scope care/surgical robots with no seed gain",
         "reflected_in_strategy_or_report": "final strategy / PubMed CLI checks"},
        {"decision_point": "QA / caveats",
         "options_considered": "drift, hygiene warnings, final-qa, filter-check",
         "evidence_or_test_used": "query_translation_drift (none); hygiene warnings cleared; final-qa 0 errors / 5 short_wildcard; filter-check no intent",
         "decision_made": "documented",
         "rationale_or_recall_risk_note": "short_wildcard warnings are phrase-anchored (e.g., robotic dog*, nursing home*) and safe",
         "reflected_in_strategy_or_report": "Rationale QA / Reporting notes"},
    ],

    "mesh_derived_from_seed_records": ("Seeds 29282989 / 29165558 / 29563027 were assigned Robotics, Long-Term Care, Nursing Homes, Dementia, Pets, "
                                       "Play and Playthings, Motor Activity, and Sleep. Robotics plus Long-Term Care / Nursing Homes informed both blocks. "
                                       "Pets and Play and Playthings were reviewed but rejected as too broad. Dementia was NOT added because the population is intentionally unrestricted."),

    "atm_translations": [
        {"query": "Robotics[Mesh]", "translation": "Robotics[MeSH Terms]", "added_explicitly": "yes"},
        {"query": "PARO[tiab] / AIBO[tiab] / Pleo[tiab]", "translation": "mapped as Title/Abstract terms", "added_explicitly": "yes"},
        {"query": "NeCoRo[tiab] / JustoCat[tiab]", "translation": "0 records, dropped from translation", "added_explicitly": "no - removed"},
        {"query": "full topic-only strategy", "translation": "clean - no broad All-Fields fallback and no quoted-phrase-not-found after cleanup", "added_explicitly": "n/a"},
    ],

    "pubmed_cli_checks": {
        "Robopet - MeSH only (Robotics[Mesh])": 53908,
        "Robopet - tiab only": 1930,
        "Robopet - combined block": 54990,
        "Setting - MeSH only": 78298,
        "Setting - tiab only": 88784,
        "Setting - combined block": 120728,
        "Final combined topic-only strategy": 369,
        "robot*[tiab] alone": 105445,
        "robot*[tiab] AND setting": 488,
        "FULL + robot*[tiab] (reserve, rejected)": 499,
        "PARO[tiab] AND setting": 54,
        "AIBO[tiab] AND setting": 2,
        "Differential robot*-only-adds (sampled 15; mostly out of scope)": "approx 130",
    },

    "tiab_expansion": {
        "pre_mesh_brainstorm_required": "Yes - robopet is a technology / psychosocial concept weakly covered by MeSH (only the broad Robotics descriptor); the setting has good MeSH but many lay synonyms.",
        "domain_framing_question_asked": "Folded into the concept-gate robot-breadth question; the user chose robotic pets + companion / social robots (not all social / assistive robots).",
        "brainstormed_vocabulary_families_accepted": "pet / animal-form robots; companion / social / socially-assistive robots; named devices PARO / AIBO / Pleo; care-home / LTC / residential-care / aged-care / assisted-living setting families.",
        "brainstormed_vocabulary_families_rejected": "humanoid robots (NAO / Pepper); bare robot*; smart-home / ambient-assisted-living technology.",
        "brainstormed_vocabulary_families_deferred": "convalescent home / geriatric hospital (low yield; not added).",
        "mesh_entry_derived_tiab_variants_added": "companion robot*, social robot*, socially assistive robot*; old age home*, homes for the aged, skilled nursing.",
        "seed_derived_tiab_variants_added": "PARO (robotic seal), companion robot, social robot, long term care, nursing home, residential aged care.",
        "sample_record_derived_tiab_variants_added": "not performed (sampling was used for relevance / noise judgement, not term harvesting).",
        "acronyms_and_abbreviations_added": "PARO, AIBO, Pleo.",
        "acronyms_and_abbreviations_tested_but_rejected": "NeCoRo, JustoCat (0 PubMed records); bare LTC / SNF / RACF not added (covered by phrases; acronym noise risk).",
        "singular_plural_variants_added": "wildcards cover plurals: nursing home*, care home*, robotic pet*, companion robot*, robopet*.",
        "spelling_variants_added": "none required (US / UK spellings align for these terms).",
        "hyphenation_variants_added": "pet-type robot*, pet-like robot*; the hyphenated long-term care tiab phrase was removed as a PubMed-normalized duplicate of the unhyphenated form.",
        "proximity_expressions_added": "none.",
        "proximity_expressions_tested_but_rejected": "Not needed - word-order variants are captured explicitly (robotic pet / pet robot; robotic animal / animal robot) and the phrases are tight; MeSH + phrase coverage is sufficient.",
        "wildcard_stems_added": "robopet*, robotic pet*, pet robot*, robotic dog*, robotic cat*, robotic seal*, companion robot*, social robot*, nursing home*, care home*, nursing facilit*, residential facilit*, residential home*, old age home*, rest home*, intermediate care facilit*.",
        "wildcard_stems_tested_but_rejected": "bare robot*[tiab] (105,445 alone; broadens beyond robopets and adds surgical / care-robot noise).",
    },

    "rationale": {
        "mesh_choices": "Robotics[Mesh] is the only robopet-relevant descriptor (no PARO / robopet MeSH exists); included exploded because the care-home AND removes the surgical-robot descendant. Pets and Play and Playthings (seed-assigned) were rejected as denoting real animals / toys. For the setting, specific facility descriptors were accepted and Residential Facilities was NOT exploded (Orphanages / Halfway Houses / Group Homes are out of scope).",
        "text_word_choices": "Because the Robotics anchor is broad, specificity is carried by tiab robopet / companion / social-robot phrases and device names; setting tiab covers lay synonyms and recent un-indexed records. Bare robot* was rejected on differential-sample evidence.",
        "pre_mesh_vocabulary_domain_choices": "Robot-breadth framing was resolved with the user (robopets + companion / social robots). Humanoid-only and all-robot framings were excluded to honour scope.",
        "concept_gate_and_omitted_block_choices": "Two essential AND blocks only. The outcome (health / well-being) was omitted (user) as too broad and is screened later. Population sub-type (dementia / aged) was omitted (user) to avoid overfitting to dementia-only seeds. The plush-toy comparator and study design were omitted to protect recall.",
        "methodological_filters_or_limits": "None. filter-check found no study-design / evidence-type intent; this is a high-sensitivity scoping / evidence-map style search.",
        "sensitivity_vs_precision": "The sensitive design was chosen (369 records, all seeds retrieved). A reserve broadening with robot*[tiab] (499) was rejected because the extra ~130 records are mostly out of scope. No focused / precision variant was needed at this size.",
        "qa": "query_translation_drift: none. Final hygiene cleared all warnings (removed dead phrase assistive social robot*, dead devices NeCoRo / JustoCat, and the hyphen duplicate). final-qa: 0 errors and 5 short_wildcard warnings, all phrase-anchored (e.g., robotic dog*, nursing home*) and therefore safe. filter-check: no methodological filter required.",
    },

    "press_2015_element_coverage": {
        "1": {"coverage": "addressed", "notes": "Review question translated into 2 essential concepts (Search structure)."},
        "2": {"coverage": "addressed", "notes": "Boolean OR within blocks, AND across blocks; proximity considered and not needed (tiab expansion log)."},
        "3": {"coverage": "addressed", "notes": "MeSH sweeps + tree / explosion decisions (NCBI CLI work)."},
        "4": {"coverage": "addressed", "notes": "tiab phrases, wildcards, and device names harvested and tested."},
        "5": {"coverage": "addressed", "notes": "Final hygiene: warnings cleared, duplicate removed, parentheses / line breaks validated via a query file."},
        "6": {"coverage": "addressed", "notes": "Limits and filters: none applied; filter-check confirmed no filter intent."},
    },

    "seed_validation": {
        "seed_pmids_tested": ["29282989", "29165558", "29563027"],
        "retrieved": ["29282989", "29165558", "29563027"],
        "missed": "none (0 missed)",
        "reason_for_misses": "none - all 3 retrieved",
        "revisions_made_after_seed_testing": "No revisions were needed for seed retrieval; only hygiene edits (removed 1 dead phrase, 2 dead device names, 1 hyphen duplicate). Count stayed at 369 and seeds stayed 3/3.",
        "seeds_judged_out_of_scope": "5181659 (1967 'Surgical treatment of myocardial ischemia') - dropped as a mistyped / off-topic PMID per the user.",
    },

    "peer_review_attention_points": [
        "Robotics[Mesh] is broad (all robotics); confirm that reliance on tiab specificity plus the decision to reject bare robot*[tiab] matches the review scope (robopets + companion robots, not all care / assistive robots).",
        "The setting block uses specific facility descriptors and excludes exploded Residential Facilities (Orphanages / Halfway Houses / Group Homes); confirm no in-scope generic 'residential care' records are missed beyond tiab coverage.",
        "The outcome (health and well-being) and the dementia / older-adult population were intentionally omitted for sensitivity - confirm this matches the protocol; screening will handle outcomes.",
    ],

    "reporting_notes": {
        "database": "PubMed",
        "date_searched": "2026-05-29",
        "limits_filters_validated_filters_used": "None",
        "restrictions_and_justifications": "No date, language, age, species, or publication-type restrictions were applied, to maximise recall.",
        "audit_workbook": "not exported",
        "remaining_caveats": ("The seed set is narrow (all PARO / dementia / one research group) and was used only as a recall check, not to tune terms; "
                              "Robotics[Mesh] is broad, so precision rests on the AND with the setting block plus tiab specificity; 5 phrase-anchored short_wildcard "
                              "warnings were accepted; the brand-new Nursing Home Residents[Mesh] (2026) will have few indexed records yet; this is a single-database PubMed search only."),
        "other_databases": "Database-specific strategies for Ovid MEDLINE, Embase, CENTRAL, CINAHL, and grey literature were not requested and not built; translate separately before relying on them.",
    },
}

with open('audit_robopets-care-homes_2026-05-29.json', 'w', encoding='utf-8') as fh:
    json.dump(audit, fh, indent=2, ensure_ascii=False)
print("wrote audit_robopets-care-homes_2026-05-29.json")
