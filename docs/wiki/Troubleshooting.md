# Troubleshooting and FAQ

## The app does not start

- **Python not found (source install):** install Python 3.11+ and reopen the terminal. The Windows release installer includes its runtime.
- **npm not found (source install):** install Node.js LTS. Node is not required for the packaged Windows release.
- **First-run setup is incomplete:** confirm internet access, then rerun the launcher. If a partial setup remains, remove the incomplete `.venv` or `node_modules` directory and retry.
- **Port is occupied:** quit another IdeaMiner process. If the launcher selected alternate ports, open the exact address it printed.
- **Browser did not open:** wait until the launcher reports that services are ready, then visit the displayed web address manually.

## My ideas or figures are missing

Check which local database file the launcher reports; separate installations may use separate databases. For copied figures, check the matching `data/assets/` folder. A JSON export carries idea records and references, not the contents of external files or all internal assets.

## Agent calls are unavailable

Confirm that the selected provider profile has a model and valid endpoint, and that the credential is available in the current operating-system account's vault. Check network access to that provider. Core IdeaMiner features do not require an Agent profile.

## SSH host needs attention

Confirm host/user/port and network access. Verify the server fingerprint through a trusted channel, then add the host to your SSH `known_hosts` using your normal SSH tooling. Do not bypass an unknown or changed host-key warning.

## An update check cannot reach GitHub

Check the network and retry from **Version and updates**. The local app and database remain available while the release service is unreachable. You can also download a release from [GitHub Releases](https://github.com/dykuang/idea-manager/releases).

## Where can I report an issue?

Open an issue on the [IdeaMiner GitHub repository](https://github.com/dykuang/idea-manager/issues). Do not attach a database, logs, screenshots, or research files unless you have reviewed and intentionally removed private information.

