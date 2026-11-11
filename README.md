# GOAT status page

The public page at the address GitHub Pages shows for this repository. A workflow rebuilds it every 30 minutes from the GOAT-IQ Goat Tracker board.

The page shows each feature's tasks by title, with their board Status (Done, In Review, In Progress, Blocked, Ready, Backlog), Size, Priority, Release and Area, and the totals built from them. Task descriptions, people and waiting reasons stay on the board.

| File | What it is |
|---|---|
| `scripts/build.py` | Reads the board and writes `site/index.html` and `site/status.json` |
| `scripts/template.html` | The page's design; `build.py` fills in the numbers |
| `.github/workflows/publish.yml` | Runs the build and publishes `site/` with GitHub Pages |

The workflow reads the board with the `GOAT_BOARD_TOKEN` secret, a read-only token for the GOAT-IQ project and goat-tracker issues.

To rebuild by hand: **Actions** → **Publish status page** → **Run workflow**.
