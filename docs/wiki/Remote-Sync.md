# Remote project-file sync

The **Remote** panel transfers one selected project's workspace files and linked attachments between this machine and a remote host over SSH/SFTP. The Ubuntu IdeaMiner application does not need to be running remotely.

## Add a remote profile

Save a display name, SSH host, user, port, and remote root folder. IdeaMiner uses your current SSH configuration, keys, or SSH agent; it does not store private keys or passphrases. Check that the server fingerprint is trusted through a separate channel and present in `known_hosts`. IdeaMiner does not silently accept unknown or changed host keys. The panel checks SSH reachability when opened and periodically while visible.

## Choose a project and direction

Select a local project and choose **Push** or **Pull** for each run. The remote project folder is named from a sanitized project name beneath the configured root. Sync includes the project workspace and linked attachments. If a project has no configured workspace, choose a local folder when prompted.

## Preview before transfer

Review the file list, sizes, and content-change status before executing. Identical files are skipped. Changed destination files require selection before overwrite. Destination-only files remain in place by default; select deletion only when you intentionally want them removed. Paths are constrained to the selected project root, and external symlinks are not followed.

If a transfer is interrupted, inspect the project state and run a new preview before retrying. A subsequent run should compare actual file contents and transfer only what is still needed.

## What sync does not copy

Remote Sync is not database replication. It does not transfer the SQLite library, ideas, tags, relations, Agent sessions, or project metadata. Use JSON export/import for library records and maintain independent backups for each machine.

