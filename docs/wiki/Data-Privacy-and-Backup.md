# Data, privacy, backup, and portability

## Where data lives

The SQLite database is the canonical source of truth. A source checkout normally stores it at `data/ideaminer.db`. The Windows installer keeps the database outside the replaceable application directory, under `%LOCALAPPDATA%\\IdeaMiner\\data\\ideaminer.db`.

Copied figures and uploaded attachments are stored under the local data folder, commonly `data/assets/`. Agent conversation history, profile settings, feedback, and other local application state may also be stored alongside the library. Do not commit the contents of `data/` to Git.

## Back up safely

1. Close IdeaMiner cleanly.
2. Copy the SQLite database and the matching assets folder to a private backup location.
3. Keep backups protected like your original research records.
4. Periodically verify that a backup can be opened or restored.

For the Windows installer, use **Uninstall → Keep only the database** only when you intentionally want to remove the app and other local IdeaMiner data. Make a separate backup first if you need figure assets, settings, or agent history; that option keeps the SQLite database only.

## JSON and Markdown exports

Use **Export → JSON** to exchange structured library records, including projects, idea text, tags, and typed relations. Treat the export as private research data. Import previews conflicts and provides merge choices. Markdown export is designed for reading. Local attachment contents are not bundled in these exports; they retain references/metadata rather than copying external files.

## What may leave the machine

Core capture, search, relations, experiments, and Gap Radar operate against the local library. Online Agent runs send only the selected context to the configured provider. Explicitly selected local files may be included. Local-file references alone do not upload the referenced contents. Remote Sync transfers selected project workspace files and linked attachments over SSH when you start a run.

## Moving between machines

Use JSON export/import for idea records. Use the **Remote** panel for a project's workspace files and attachments. These are separate operations: project-file sync does not sync SQLite records, idea metadata, or relations. Keep a current database backup on each machine.

