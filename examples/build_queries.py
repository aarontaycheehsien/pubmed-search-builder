"""Build reusable PubMed query blocks + a batch count file for the
robopets / care-home strategy. All strings use double-quoted PubMed
phrases, so Python single-quoted literals keep them clean."""
import json

# --- Robopet / companion-robot intervention block ---------------------------
R_MESH = '"Robotics"[Mesh]'
R_TIAB_INNER = (
    'robopet*[tiab] OR "robot pet*"[tiab] OR "pet robot*"[tiab] '
    'OR "robotic pet*"[tiab] OR "robotic animal*"[tiab] OR "animal robot*"[tiab] '
    'OR "robotic dog*"[tiab] OR "robotic cat*"[tiab] OR "robotic seal*"[tiab] '
    'OR "robotic companion*"[tiab] OR "companion robot*"[tiab] '
    'OR "social robot*"[tiab] OR "socially assistive robot*"[tiab] '
    'OR "therapeutic robot*"[tiab] '
    'OR "zoomorphic robot*"[tiab] OR "artificial pet*"[tiab] '
    'OR "pet-type robot*"[tiab] OR "pet-like robot*"[tiab] '
    'OR PARO[tiab] OR AIBO[tiab] OR Pleo[tiab]'
)
R_TIAB = '(' + R_TIAB_INNER + ')'
R_ALL = '(' + R_MESH + ' OR ' + R_TIAB_INNER + ')'

# --- Care-home / long-term-care setting block -------------------------------
S_MESH_INNER = (
    '"Nursing Homes"[Mesh] OR "Homes for the Aged"[Mesh] '
    'OR "Assisted Living Facilities"[Mesh] OR "Long-Term Care"[Mesh] '
    'OR "Nursing Home Residents"[Mesh]'
)
S_TIAB_INNER = (
    '"nursing home*"[tiab] OR "nursing facilit*"[tiab] OR "care home*"[tiab] '
    'OR "residential care"[tiab] OR "residential facilit*"[tiab] '
    'OR "residential home*"[tiab] OR "aged care"[tiab] '
    'OR "long term care"[tiab] '
    'OR "old age home*"[tiab] OR "rest home*"[tiab] OR "assisted living"[tiab] '
    'OR "skilled nursing"[tiab] OR "homes for the aged"[tiab] '
    'OR "intermediate care facilit*"[tiab]'
)
S_MESH = '(' + S_MESH_INNER + ')'
S_TIAB = '(' + S_TIAB_INNER + ')'
S_ALL = '(' + S_MESH_INNER + ' OR ' + S_TIAB_INNER + ')'

FULL = R_ALL + '\nAND\n' + S_ALL

# reusable block + strategy files
open('robopet_block.txt', 'w', encoding='utf-8').write(R_ALL + '\n')
open('setting_block.txt', 'w', encoding='utf-8').write(S_ALL + '\n')
open('full_strategy.txt', 'w', encoding='utf-8').write(FULL + '\n')

# differential set: records bare robot*[tiab] would ADD beyond the scoped block
DIFF_ROBOTSTAR = '(robot*[tiab] AND ' + S_ALL + ') NOT ' + R_ALL
open('diff_robotstar.txt', 'w', encoding='utf-8').write(DIFF_ROBOTSTAR + '\n')

batch = [
    {"label": "R_mesh_only", "query": R_MESH},
    {"label": "R_tiab_only", "query": R_TIAB},
    {"label": "R_all", "query": R_ALL},
    {"label": "S_mesh_only", "query": S_MESH},
    {"label": "S_tiab_only", "query": S_TIAB},
    {"label": "S_all", "query": S_ALL},
    {"label": "FULL_topic_only", "query": FULL},
    {"label": "noise_robotstar_alone", "query": "robot*[tiab]"},
    {"label": "noise_PARO_alone", "query": "PARO[tiab]"},
    {"label": "noise_AIBO_alone", "query": "AIBO[tiab]"},
    {"label": "robotstar_AND_setting", "query": "(robot*[tiab] AND " + S_ALL + ")"},
    {"label": "PARO_AND_setting", "query": "(PARO[tiab] AND " + S_ALL + ")"},
    {"label": "AIBO_AND_setting", "query": "(AIBO[tiab] AND " + S_ALL + ")"},
    {"label": "FULL_plus_robotstar", "query": "((" + R_ALL + " OR robot*[tiab]) AND " + S_ALL + ")"},
]
open('queries_blocks.json', 'w', encoding='utf-8').write(json.dumps(batch, indent=2))
print("wrote robopet_block.txt, setting_block.txt, full_strategy.txt, queries_blocks.json")
print("batch labels:", ", ".join(b["label"] for b in batch))
