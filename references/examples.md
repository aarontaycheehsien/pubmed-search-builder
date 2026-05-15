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
