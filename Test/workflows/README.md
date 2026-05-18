# Workflows

Markdown SOPs that define how the agent should accomplish a task. These are the instructions layer of the WAT framework.

## Conventions

- **Naming:** `verb_noun.md` — e.g., `scrape_website.md`, `export_to_sheets.md`, `summarize_emails.md`
- **Keep them current.** When a tool changes, a rate limit is discovered, or a better method is found — update the workflow. These are living documents.
- **Don't create or overwrite without asking** unless explicitly told to.

## Workflow Template

Copy this into a new file and fill it in:

```markdown
# [Workflow Name]

## Objective
One sentence: what does this workflow accomplish and why?

## Inputs
- `input_name` — description and where it comes from

## Steps
1. Step one — reference the tool: `tools/script_name.py`
2. Step two
3. ...

## Tools Used
- `tools/script_name.py` — what it does in this context

## Expected Output
- Where does the result go? (Google Sheet link, file path, etc.)
- What does success look like?

## Edge Cases & Known Issues
- Rate limit on X API: use batch endpoint (see tools/script.py)
- If Y fails: check Z first
```

## Example Workflows to Build

Add workflows here as you create them. Each line is a link:

- *(none yet — add your first workflow)*
