# Examples

These examples show patterns, not universal final strategies. Always use the MeSH and PubMed scripts for the user's actual topic.

## Example 1: Pressure ulcer concept block

```text
(
  "Pressure Ulcer"[Mesh]
  OR "pressure ulcer"[tiab]
  OR "pressure ulcers"[tiab]
  OR "pressure injury"[tiab]
  OR "pressure injuries"[tiab]
  OR "pressure sore"[tiab]
  OR "pressure sores"[tiab]
  OR "decubitus ulcer"[tiab]
  OR "decubitus ulcers"[tiab]
  OR "decubitus sore"[tiab]
  OR "decubitus sores"[tiab]
  OR bedsore*[tiab]
  OR "bed sore"[tiab]
  OR "bed sores"[tiab]
  OR "skin breakdown"[tiab]
)
```

## Example 2: Neuromodulation concept block

```text
(
  "Transcranial Magnetic Stimulation"[Mesh]
  OR "Transcranial Direct Current Stimulation"[Mesh]
  OR "Deep Brain Stimulation"[Mesh]
  OR "Electric Stimulation Therapy"[Mesh]
  OR "transcranial magnetic stimulation"[tiab]
  OR "repetitive transcranial magnetic stimulation"[tiab]
  OR TMS[tiab]
  OR rTMS[tiab]
  OR "transcranial direct current stimulation"[tiab]
  OR "transcranial direct-current stimulation"[tiab]
  OR tDCS[tiab]
  OR "transcranial electrical stimulation"[tiab]
  OR "transcranial electric stimulation"[tiab]
  OR "noninvasive brain stimulation"[tiab]
  OR "non-invasive brain stimulation"[tiab]
  OR NIBS[tiab]
  OR neuromodulat*[tiab]
  OR neurostimulat*[tiab]
  OR "deep brain stimulation"[tiab]
  OR DBS[tiab]
  OR "motor cortex stimulation"[tiab]
  OR MCS[tiab]
)
```

## Example 3: Telehealth and type 2 diabetes

```text
(
  "Diabetes Mellitus, Type 2"[Mesh]
  OR "type 2 diabetes"[tiab]
  OR "type II diabetes"[tiab]
  OR T2DM[tiab]
  OR diabet*[tiab]
)
AND
(
  "Telemedicine"[Mesh]
  OR telemedicine[tiab]
  OR telehealth[tiab]
  OR tele-health[tiab]
  OR "remote consultation"[tiab]
  OR "remote consultations"[tiab]
  OR "virtual care"[tiab]
  OR "digital health"[tiab]
  OR mHealth[tiab]
  OR "mobile health"[tiab]
  OR eHealth[tiab]
  OR "electronic health"[tiab]
)
```

## Example 4: Missed seed PMID diagnosis

If a seed PMID is missed, check whether each concept block retrieves it.

Example diagnostic pattern:

```text
12345678[uid] AND (concept 1 block)
12345678[uid] AND (concept 2 block)
12345678[uid] AND (concept 3 block)
```

If one block fails, inspect the title, abstract, and MeSH headings of that PMID and revise the failing block.


## Example 5: Adding a validated RCT filter

Only add a trial filter if the review question or protocol requires randomised or controlled trials.

Topic-only strategy:

```text
(
  "Diabetes Mellitus, Type 2"[Mesh]
  OR "type 2 diabetes"[tiab]
  OR T2DM[tiab]
  OR diabet*[tiab]
)
AND
(
  "Telemedicine"[Mesh]
  OR telemedicine[tiab]
  OR telehealth[tiab]
  OR "remote consultation"[tiab]
  OR "virtual care"[tiab]
)
```

Add the Cochrane HSSS sensitivity-maximising RCT filter in PubMed format:

```text
AND
(
  (
    randomized controlled trial[pt]
    OR controlled clinical trial[pt]
    OR randomized[tiab]
    OR placebo[tiab]
    OR drug therapy[sh]
    OR randomly[tiab]
    OR trial[tiab]
    OR groups[tiab]
  )
  NOT
  (
    animals[mh] NOT humans[mh]
  )
)
```

Before retaining the filter, test:

```text
(topic-only strategy) AND (seed PMID block)
```

and:

```text
(topic-only strategy) AND (RCT filter) AND (seed PMID block)
```

If an in-scope seed PMID is lost only after adding the RCT filter, report the loss and reconsider the filter choice, version, or whether a filter should be used.

## Example 6: Intervention question - statins in liver cirrhosis (PICO walk-through)

**Question:** Do statins reduce progression or complications in patients with liver cirrhosis?

**Framework choice:** PICO (intervention effectiveness review).

**Candidate elements:**

| Slot | Candidate |
|---|---|
| Population | Patients with liver cirrhosis |
| Intervention | Statins |
| Comparator | No statin, placebo, usual care |
| Outcome | Progression, complications, decompensation, mortality, safety |

**Concept-gate decisions:**

| Candidate | Role | Decision | Reason |
|---|---|---|---|
| Liver cirrhosis | Population | Essential `AND` block | Central condition; reliably indexed |
| Statins | Intervention | Essential `AND` block | Central intervention; reliably indexed |
| No statin / placebo / usual care | Comparator | Omitted concept | Usually implicit and inconsistently reported ([Frandsen 2020](https://doi.org/10.1016/j.jclinepi.2020.07.005)) |
| Progression, complications | Outcome | Screening-only | Likely inconsistently reported; risk of missing relevant records |
| Mortality, safety | Outcome | Screening-only, optional separate strand for adverse events | High recall risk if required |

**Recommended structure:**

```text
(
  "Liver Cirrhosis"[Mesh]
  OR "Hepatic Cirrhosis"[Mesh]
  OR cirrhosis*[tiab]
  OR cirrhotic*[tiab]
  OR "liver fibrosis"[tiab]
  OR "hepatic fibrosis"[tiab]
)
AND
(
  "Hydroxymethylglutaryl-CoA Reductase Inhibitors"[Mesh]
  OR statin*[tiab]
  OR "HMG CoA reductase inhibitor"[tiab]
  OR "HMG-CoA reductase inhibitor"[tiab]
  OR atorvastatin[tiab] OR simvastatin[tiab] OR rosuvastatin[tiab]
  OR pravastatin[tiab] OR fluvastatin[tiab] OR lovastatin[tiab]
  OR pitavastatin[tiab]
)
```

**Screening-only concepts:** progression, decompensation, complications, mortality, adverse events, comparator type.

Use the actual `mesh_tool.py sweep` and `pubmed_tool.py` workflow in `workflow.md` to harvest the full term sets and validate against seeds.

## Example 7: Exposure question - dietary fibre and colorectal cancer risk (PECO walk-through)

**Question:** Does dietary fibre intake associate with colorectal cancer risk in adults?

**Framework choice:** PECO (exposure / association review). Comparator is rarely informative in dietary epidemiology because intake is a continuous exposure.

**Candidate elements:**

| Slot | Candidate |
|---|---|
| Population | Adults |
| Exposure | Dietary fibre intake |
| Comparator | Lower fibre intake (implicit) |
| Outcome | Colorectal cancer (incidence, risk) |

**Concept-gate decisions:**

| Candidate | Role | Decision | Reason |
|---|---|---|---|
| Adults | Population | Omitted concept | Demographic filter, not central; handled at screening |
| Dietary fibre | Exposure | Essential `AND` block | Central exposure |
| Lower fibre intake | Comparator | Omitted concept | Implicit; not reliably searchable |
| Colorectal cancer | Outcome | Essential `AND` block | Defines the disease endpoint; reliably indexed |

**Recommended structure:**

```text
(
  "Dietary Fiber"[Mesh]
  OR "dietary fiber"[tiab] OR "dietary fibre"[tiab]
  OR "dietary fibres"[tiab] OR "dietary fibers"[tiab]
  OR "dietary roughage"[tiab]
  OR fiber[tiab] OR fibre[tiab]
  OR cellulose[tiab] OR pectin*[tiab]
  OR "whole grain"[tiab] OR "whole grains"[tiab]
  OR "whole-grain"[tiab]
)
AND
(
  "Colorectal Neoplasms"[Mesh]
  OR "Colonic Neoplasms"[Mesh]
  OR "Rectal Neoplasms"[Mesh]
  OR "colorectal cancer"[tiab] OR "colorectal cancers"[tiab]
  OR "colon cancer"[tiab] OR "colon cancers"[tiab]
  OR "rectal cancer"[tiab] OR "rectal cancers"[tiab]
  OR "bowel cancer"[tiab] OR "bowel cancers"[tiab]
  OR "colorectal neoplasm"[tiab] OR "colorectal neoplasms"[tiab]
  OR "colorectal carcinoma"[tiab] OR "colorectal carcinomas"[tiab]
  OR "colorectal adenocarcinoma"[tiab]
)
```

**Screening-only concepts:** adult age range, exposure dose categories, follow-up duration, specific subsite (colon vs rectum).

Note: in PECO, the Outcome was kept as an essential `AND` block because it defines the disease endpoint and is reliably indexed (cancer terms have stable MeSH and consistent author wording). This is the exception to the general default that Outcome is omitted - confirm via seed retrieval testing.

## Example 8: Scoping question - digital health for stroke rehabilitation in LMICs (PCC walk-through)

**Question:** What digital health interventions have been used for stroke rehabilitation in low- and middle-income countries?

**Framework choice:** PCC (Population, Concept, Context). Scoping reviews are typically broader and less restrictive than intervention reviews.

**Candidate elements:**

| Slot | Candidate |
|---|---|
| Population | Stroke patients undergoing rehabilitation |
| Concept | Digital health interventions |
| Context | Low- and middle-income countries |

**Concept-gate decisions:**

| Candidate | Role | Decision | Reason |
|---|---|---|---|
| Stroke + rehabilitation | Population | Essential `AND` block | Central population; reliably indexed |
| Digital health interventions | Concept | Essential `AND` block | Central concept |
| LMICs | Context | Optional `AND` block, tested as variant | Country-level filters can miss records that do not name the country in the title/abstract; test the impact and consider screening-only handling |

**Recommended structure (sensitive variant, omitting Context):**

```text
(
  "Stroke Rehabilitation"[Mesh]
  OR "Stroke"[Mesh]
  OR stroke*[tiab]
  OR "cerebrovascular accident"[tiab]
  OR CVA[tiab]
  OR "brain infarction"[tiab]
)
AND
(
  "Telemedicine"[Mesh]
  OR "Telerehabilitation"[Mesh]
  OR "Digital Health"[Mesh]
  OR "Mobile Applications"[Mesh]
  OR "Wearable Electronic Devices"[Mesh]
  OR telerehab*[tiab]
  OR telehealth[tiab] OR telemedicine[tiab]
  OR "digital health"[tiab] OR "mobile health"[tiab]
  OR mHealth[tiab] OR eHealth[tiab]
  OR "virtual reality"[tiab]
  OR "mobile app"[tiab] OR "mobile apps"[tiab]
  OR "wearable device"[tiab] OR "wearable devices"[tiab]
  OR "smartphone application"[tiab]
)
```

**Focused variant adding Context:** add a validated LMIC filter as a third block (see `validated-methodological-filters-and-hedges.md` for Cochrane EPOC LMIC filter sources). Test sensitive and focused variants against seeds. If LMIC restriction loses in-scope seeds, prefer the sensitive variant and handle country at screening.

**Screening-only concepts:** specific rehabilitation outcome (motor, cognitive, speech), implementation barriers, country list within LMIC.
