# Eval suite results

Generated 2026-07-25T05:14:16Z against 10 of 20 fixtures.

`recall` is measured over gold PMIDs that exist in PubMed; records the source review found only in other databases are excluded from the denominator. `NNR` is total hits ÷ gold retrieved — a workload proxy, not precision.

**Read the `source` column before the recall column.**

| source | meaning |
|---|---|
| `generated` | the skill built this strategy — the only rows that measure the skill |
| `baseline` | strategy hand-authored for the fixture |
| `naive` | compiled from the fixture's protocol term families: no MeSH, no expansion, no critic loop. A floor. |

| topic | suite | source | gold (in PubMed) | retrieved | recall | hits | NNR | bottleneck block |
|---|---|---|---:|---:|---:|---:|---:|---|
| Medeiros-2022-School-based food and nutrition education interventions for adolescent food consumption | 2022-custom | `baseline` | 9 | 8 | 88.9% | 37,813 | 4727 | — |
| gao-2026-Immune checkpoint inhibitors | 2026-custom | `naive` | 11 | 8 | 72.7% | 2,342 | 293 | Immune checkpoint inhibitors |
| CD010657 | clef-tar-2018 | `naive` | 35 | 32 | 91.4% | 1,173 | 37 | Vesicoureteral reflux |
| CD011431 | clef-tar-2018 | `naive` | 26 | 21 | 80.8% | 2,623 | 125 | Rapid diagnostic tests |
| CD011926 | clef-tar-2018 | `baseline` | 29 | 28 | 96.6% | 2,703 | 97 | C2 sepsis / bloodstream infection |
| Liu_2023_VR_nursing | education-health | `naive` | 6 | 6 | 100.0% | 937 | 156 | Nursing students / nursing education |
| Appenzeller-Herzog_2019 | synergy | — | — | — | **failed** | — | — | protocol is unrefined: concept 'review-topic' has a single t |
| Bos_2018 | synergy | `naive` | 9 | 6 | 66.7% | 7,363 | 1227 | Cerebral small vessel disease / MRI markers |
| Brouwer_2019 | synergy | — | — | — | **failed** | — | — | protocol is unrefined: concept 'review-topic' has a single t |
| Donners_2021 | synergy | `naive` | 15 | 15 | 100.0% | 4,649 | 310 | Emicizumab |
| Jeyaraman_2020 | synergy | — | — | — | **failed** | — | — | protocol is unrefined: concept 'review-topic' has a single t |
| Kwok_2020 | synergy | — | — | — | **failed** | — | — | protocol is unrefined: concept 'review-topic' has a single t |
| Meijboom_2021 | synergy | — | — | — | **failed** | — | — | protocol is unrefined: concept 'review-topic' has a single t |
| Menon_2022 | synergy | — | — | — | **failed** | — | — | protocol is unrefined: concept 'review-topic' has a single t |
| Muthu_2022 | synergy | `naive` | 6 | 6 | 100.0% | 1,197 | 200 | Rotator cuff tear/repair |
| Oud_2018 | synergy | — | — | — | **failed** | — | — | protocol is unrefined: concept 'review-topic' has a single t |
| Smid_2020 | synergy | `naive` | 14 | 11 | 78.6% | 4,336 | 394 | Structural equation / latent-variable model family |
| van_de_Schoot_2018 | synergy | — | — | — | **failed** | — | — | protocol is unrefined: concept 'review-topic' has a single t |
| van_Dis_2020 | synergy | — | — | — | **failed** | — | — | protocol is unrefined: concept 'review-topic' has a single t |
| Welling_2021 | synergy | — | — | — | **failed** | — | — | protocol is unrefined: concept 'review-topic' has a single t |

## By strategy source

| source | topics | gold in PubMed | retrieved | mean recall | median | min | max | topics <80% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `baseline` | 2 | 38 | 36 | 92.75% | 92.75% | 88.9% | 96.6% | 0 |
| `naive` | 8 | 122 | 105 | 86.28% | 86.1% | 66.7% | 100.0% | 3 |

## Change since the previous run

No regression across 7 comparable topics.
