# Inbox Triage Bot

A read-only inbox clerk: a daily brief of your mail, and reply drafts you approve before anything is sent.

## What it is

A small-business inbox clerk that reads one mailbox **read-only** over IMAP (it never
marks, moves or deletes mail), builds a **daily brief** (7:00 AM local, editable, or on
demand: "brief me") and **drafts replies when you ask**. Nothing is sent until you
approve each send over SMTP; mail text is treated as untrusted and it does not browse
the web. It is one Docker image built `FROM` Gold Valley Bot Core
(`goldvalleysolutions/core-bot:0.3`).

## Quick start

Only Docker is needed (Docker Desktop, Colima or Linux; amd64 or arm64):

```bash
docker pull goldvalleysolutions/inbox-triage-bot:0.2
docker run -d --name inbox-triage -p 8080:8080 -v inbox-triage-data:/data goldvalleysolutions/inbox-triage-bot:0.2
```

Open <http://localhost:8080> and complete setup (`/setup`: bot-admin login, who can use
the bot, AI model, then **Mail account**: pick Gmail, Zoho or Outlook/M365 or enter any
IMAP/SMTP host, type your email and one app password, press **Test connection**, then
run the self-test). Until a mailbox is set the bot uses four demo messages.
`curl -f http://localhost:8080/health` works before and after setup. If host port 8080
is taken, change the left side, e.g. `-p 8081:8080`.

Full walkthrough: [bot/README.md](https://github.com/goldvalleysolutions/gvs-inbox-triage-bot/blob/main/bot/README.md).

## Configuration

| Item | Value | Notes |
|---|---|---|
| Port | `8080` (container) | Map with `-p <host>:8080` |
| Volume | `/data` | `bot.db` + `bot.key` (settings, encrypted keys and app password, memory, cached mail, logs); back up both; delete the volume to start over |
| Mail account | `/setup` **Mail account** | IMAP (`IMAP_HOST`, `IMAP_PORT`, `IMAP_SENT`) read-only, SMTP (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`) for approved sends; stored encrypted in `/data` |
| Allowlist | **Admin** | Core sends only to allowlisted addresses; add a client before approving a reply to them |
| Daily brief | **Admin > Schedules**, Brief page `/r/inbox-triage/brief` | Job `daily_brief`, `daily 07:00`; Run now, Email the brief to me, retention (30 days), Forget mailbox |
| AI provider key | `/setup` or **Admin** | Anthropic, OpenAI, OpenRouter or xAI; stub model needs none. Core also reads `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `XAI_API_KEY` to preselect a provider |
| `GVS_TRUSTED_PROXIES` | optional (Core) | Comma-separated proxy IPs trusted for `X-Forwarded-Proto`; default `127.0.0.1,::1` |
| `GVS_LLM_MAX_TOKENS` | optional (Core) | Max reply tokens, 1-8192, default 1024 |

## Repo contents

| Path | What is in it |
|---|---|
| `bot/` | The bot pack copied onto Core: `Dockerfile`, `bot.yaml`, `role.md`, `skills/` (triage, daily-brief, reply-draft), `tools/inbox.py`, `services/brief.py` (daily brief job + Brief page), `theme.yaml`, `demo/` |
| `scripts/` | `verify-local.sh` (all local checks), `inbox-triage-steps.sh` (walkthrough against a built image), fake IMAP/SMTP servers and helpers |
| `tests/` | `unit/` (pytest), `e2e/` (Playwright, stub LLM, fake IMAP/SMTP) |
| `.github/workflows/` | `publish.yml` (main-only Docker Hub publish), `dockerhub-description.yml` (Docker Hub overview from this README) |

## Build and test from source

```bash
git clone https://github.com/goldvalleysolutions/gvs-inbox-triage-bot.git
cd gvs-inbox-triage-bot
docker build -f bot/Dockerfile -t goldvalleysolutions/inbox-triage-bot:0.2.0 .
scripts/verify-local.sh          # all checks; prints the Local verification block for the PR
```

Tests run this repo's `bot/` on Core from source. Point `GVS_CORE_DIR` at a gvs-core-bot
checkout at the pinned `CORE_SHA` (in `tests/e2e/conftest.py`) with its requirements
installed, or leave it unset and the e2e suite clones it into `.e2e/core`:

```bash
python -m pip install -r "$GVS_CORE_DIR/requirements.txt" -r tests/e2e/requirements.txt
python -m playwright install chromium
python -m pytest tests/unit -q
python -m pytest tests/e2e -q -p no:cacheprovider
scripts/inbox-triage-steps.sh goldvalleysolutions/inbox-triage-bot:0.2.0   # walkthrough on the built image
```

Validate the manifest from a gvs-core-bot checkout: `make lint-bot BOT=<path to this repo>/bot`.

## Versioning and releases

PRs go to `test`; only Mike merges `test` into `main`. A merge to `main` publishes
`goldvalleysolutions/inbox-triage-bot` as `X.Y.Z` and `X.Y` (never `latest`) and creates
GitHub release `vX.Y.Z`. A README change merged to `main` updates this Docker Hub
description (`dockerhub-description.yml`). The version is `version:` in `bot/bot.yaml`;
the Core pin is `core:` there and `ARG CORE` in `bot/Dockerfile`.

## License

Apache License 2.0 (declared in the image labels). Core: [gvs-core-bot LICENSE](https://github.com/goldvalleysolutions/gvs-core-bot/blob/main/LICENSE).
