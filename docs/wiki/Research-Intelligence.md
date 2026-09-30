# Research Intelligence

Research Intelligence adds three local-first tools to the idea workflow. Open **Review** to see experiment follow-ups, Research Gap Radar, and Serendipity. Configure their independent switches and thresholds in **Research Intelligence** settings.

## Micro-experiments

Log a focused trial as an experiment rather than creating another idea card. Record what was tried, result, takeaway, and status; add dataset/material, metrics, code or commit reference, custom metadata, and result figures when useful. Link an experiment to one or more ideas with roles such as `tests`, `supports`, `contradicts`, `motivated-by`, or `follow-up`.

Experiment search and repeat detection help find previous work before you run it again. Similarity is a prompt for inspection, not a claim that two experiments are equivalent. Results and links remain part of the local library.

Weekly Review can surface recently completed, inconclusive, and failed experiments, plus planned experiments that have gone untouched.

## Research Gap Radar

Gap Radar uses deterministic local rules to identify development gaps in your own library. It does not assess research quality or claim to identify gaps in published literature. Depending on your settings and library structure, it may flag:

- a promising idea with no linked experiment;
- a stalled active branch;
- an unresolved contradiction;
- a promising idea that needs evidence;
- a result without a takeaway or follow-up;
- a cluster of related ideas that may benefit from synthesis;
- a high-value idea with no relations.

Use the suggested action to log an experiment, open a lineage, add a takeaway, or synthesize a theme. Resolve, dismiss, or snooze a gap when the prompt no longer applies. Feedback memory prevents the same item from repeatedly interrupting review.

## Serendipity

**Similar but unlinked** remains the closest-neighbor finder. Serendipity is a separate, conservative cross-project discovery mode: it looks for less obvious bridges across projects, lineages, structural roles, and methodological concepts. It excludes existing links and dismissed suggestions and returns only a small set of candidates. An empty result can be useful; the feature is not expected to invent a connection every week.

For a candidate, inspect both ideas, send them to **Dream**, connect them, save the suggestion, or dismiss it. Only create a relation when the bridge is useful and concrete.

## Personalize it

In **Research Intelligence** settings, independently enable Experiments, Gap Radar, and Serendipity. Adjust stalled-branch age, suggestion count, cross-project preference, evidence checks, and visible experiment fields. Custom experiment-field definitions are stored as metadata rather than requiring a database schema change.

