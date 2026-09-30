# Ideas and research workflow

## Capture first, organize later

Use `random_chat` for a quick capture or create an idea directly in a project. IdeaMiner retains the original wording in an immutable capture field and keeps later working notes separately. Use Markdown and KaTeX in working notes. Add tags, a stage, or an attachment when it helps retrieval.

## Develop ideas with relations

Use typed relations to record why ideas connect. `develops-into` forms a development lineage; other relation types can express evidence, contradiction, inspiration, and related concepts. Open **Lineage** to inspect a development branch and **Graph** to explore a wider network. Relations are more durable than writing a card number in prose.

Use **Elaborate** to draft a possible next step. Save it as a new idea when it should become a child and preserve the original. Agent-generated changes and connections remain proposals until you accept them.

## Find and inspect ideas

- Search uses SQLite FTS5 and supports filters for projects, tags, stages, and other library fields.
- **Similar but unlinked** finds close semantic neighbors that are not yet related.
- **Tag Map** visualizes tag co-occurrence in the selected scope.
- **Focus** provides a compact navigator and stable reading pane for reviewing many cards.

## Files and figures

Attach a local file reference when you want to record where a paper, dataset, or code folder lives without copying its contents. Add figures to an idea using the figure gallery, drag-and-drop, or paste. Uploaded or pasted figures are copied into the local `data/assets/ideas/` folder; linked files remain at their original locations.

## Weekly rhythm

Open **Review** regularly. Review brings forward ideas and experiments that may need a next action. Use its prompts to update stages, finish experiment takeaways, or return to a stalled branch. The Research Intelligence settings let you disable any of its optional sections.

