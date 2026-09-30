# Agents, Dream, and Codex

IdeaMiner's core library works without a language model. Agent tools are optional, and an accepted result is always a user decision.

## Configure an Agent

Open **Agent**, choose a provider (OpenAI, Anthropic, DeepSeek, Qwen, or Local), configure the endpoint/model, and save the profile. Profiles are separate by provider. When available, keep **Remember this credential in the operating system vault** enabled so a credential is stored in the OS vault rather than the IdeaMiner database. Use **Forget saved profile** to remove the provider's saved settings and secret.

Local supports an OpenAI-compatible endpoint and may be configured with or without an API key. `.env.example` documents environment variables for unattended configuration; it is not automatically loaded.

## Context and privacy

Before a run, select the project, idea cards, or compatible local files that should provide context. Original immutable captures are excluded from online Agent context. Selected working notes and explicitly selected compatible files may be sent to the configured model provider. Review the selection before running, especially when working with unpublished or confidential research.

Agent responses are proposals. Inspect generated text and proposed relations before applying them.

## Dream

Add two to eight idea cards to **Dream**, including cards from different projects. Add an optional synthesis prompt, choose a destination project, and ask the Agent for a synthesis. Review the proposed ideas and links before saving. Accepted Dream results are connected to their source ideas so their origins remain visible.

Serendipity cards can open their ideas or pass the pair directly into Dream. Dream is useful for exploring a bridge; it does not guarantee that the bridge is scientifically sound.

## Codex MCP integration

The repository includes `ideaminer_mcp.py` as the stdio entry point and a reusable Codex skill under `integrations/codex/ideaminer`. Configure an MCP server to run the script with the repository's Python environment and repository root as its working directory. The Windows installer adds a **Connect Codex MCP** Start Menu shortcut when Codex CLI is installed.

The MCP server uses the same SQLite library as the app. It supports search, capture, edits, typed relations, moves/copies, attachments, and review checkpoints; it does not expose permanent deletion.

