# CODE ATLAS

A local source browser and repository analysis workspace.

- Index a local Git repository, public GitHub repository, or ZIP
- Inspect Python symbols, imports, calls, and complexity
- Search source and export Markdown or an SVG relationship view

## Run locally

Install Python 3.11+ and clone or download this repository. For Git imports, install Git.
Ollama is optional for the offline workflows. For AI, start Ollama with local models such as
Qwen3 4B and Nomic Embed Text.

    sh install.sh
    sh run.sh

Open http://127.0.0.1:8502. Ctrl+C stops the server.
Run \`python3 test_workflows.py\` for the workflow test.

## Scope

C, C++, Java, JavaScript, and TypeScript use Tree-sitter when the grammar packages are installed. The app falls back to heuristic extraction when they are missing. Call relationships are syntactic candidates. Secret filtering is heuristic. ZIP imports use built-in exclusions, while local Git imports use Git's ignore rules for untracked files.
The semantic search reranks up to 120 keyword-ranked candidates. AI output can be incomplete
and should be checked against the displayed evidence.

## Local data

Data is stored in \`data/\` (or \`APP_DATA_DIR\` if set). Stop the app before backing it up:

    python3 backup.py backup /absolute/path/to/new-backup
    python3 backup.py restore /absolute/path/to/existing-backup

Restore requires the data directory to be absent. To uninstall, stop the app, back up data you
want to keep, and remove the project folder. The public landing page contains project information.

## Parsers

The installer fetches Tree-sitter and the language grammars. Source is parsed as text.
Call and dependency relationships are syntactic candidates and may require human review.
