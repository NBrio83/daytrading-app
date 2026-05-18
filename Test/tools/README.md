# Tools

Python scripts that do the actual work. Each script handles one deterministic task.

## Conventions

- **One script, one task.** `scrape_single_site.py` scrapes. `export_to_sheets.py` exports. No monoliths.
- **Naming:** `verb_noun.py` — describes what the script does, not what it's for.
- **Credentials:** Read from `.env` via `python-dotenv`. Never hardcode keys.
- **Output:** Print a clear result on success, a clear error on failure. The agent reads this output to decide what to do next.
- **No side effects on dry runs:** If a script writes or posts anywhere, it should support a `--dry-run` flag.

## Standard Script Structure

```python
import os
from dotenv import load_dotenv

load_dotenv()

def main():
    # read inputs (args or env)
    # do the work
    # print result
    pass

if __name__ == "__main__":
    main()
```

## Adding a New Tool

1. Create `tools/your_script.py`
2. Reference it in the relevant workflow under `tools/`
3. Test it standalone before wiring it into a workflow
