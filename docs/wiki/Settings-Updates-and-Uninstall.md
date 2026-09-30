# Settings, updates, and uninstall

## Appearance and research settings

Use **Appearance** to select Classic or Studio, choose a light/dark/system theme, and adjust list density. These display preferences live in the current browser.

Use **Research Intelligence** settings to independently toggle Micro-experiments, Gap Radar, and Serendipity. Set the stalled-branch interval, suggestion limit, cross-project preference, evidence checks, and experiment fields to match your workflow.

## Version and updates

The top-bar version control shows the installed version. Open it to check the latest GitHub release and, on supported packaged Windows installs, start the update. Updates replace the app files while leaving the local library outside the application folder.

Source checkouts should update through their Git workflow rather than the packaged one-click updater. Back up the database before a major change.

## Uninstall on Windows

Open **Version and updates → Uninstall IdeaMiner** and choose:

- **Keep only the database** — remove the app and other IdeaMiner data while retaining the SQLite database. This does not preserve the separate figures/assets folder, profile settings, or agent history.
- **Remove everything** — remove the app and IdeaMiner data in its local data folder.

Project workspace directories are left untouched. Make a backup before uninstalling if anything in the local data folder matters to you.

