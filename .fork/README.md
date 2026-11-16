# Customized fork maintenance

`kopiro` retains the customized application. Feature branches for upstream pull requests start
from upstream `main` and exclude this directory and the synchronization workflow.

The synchronization workflow runs daily at 03:17 UTC and supports manual dispatch. It merges
upstream into a temporary candidate and explicitly runs the existing `ci.yml` workflow on that
candidate. Only passing candidates advance `kopiro`. Conflicts, failed checks and concurrent
changes leave the customized branch untouched. Failed candidates remain available for diagnosis.
Synchronization does not install packages or publish releases.

`check_sync.py --repo OWNER/REPOSITORY --install` installs a macOS launchd health check. It checks
hourly and dispatches synchronization if no run has started for 30 hours. It also re-enables a
workflow disabled by GitHub's inactivity policy. It respects manually disabled workflows.
It uses the existing `gh` login and stores no authentication values.

The `qa` directory retains screenshots from the macOS simulator against disposable Plex media.
The movie confirmation covers all file versions. The episode confirmation names the show,
season and episode. Both dialogs default to Cancel.

Filmography credits now offer one Add to Watchlist action on hold, including titles with no
library copy. The shared menu and Watchlist write path also coexist with media deletion.
`qa/filmography-hold-menu.png` shows the add-only menu on a catalog-only title;
`qa/filmography-watchlist-added.png` shows the same page after a successful mock Plex write.
