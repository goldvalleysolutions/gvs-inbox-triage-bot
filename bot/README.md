# Inbox Assistant in a Box

A small-business inbox clerk that proves a product role from `new-box`: the
owner pastes an email, the box triages it and drafts a reply. One image,
`/setup`, memory, allowlisted tools, and the Gold Valley Solutions gold theme.
There is no IMAP or POP — the owner provides the message.

_Screenshot: first-boot `/setup` and the chat page after the self-test (this PR)._

## Up and running in 5 minutes

The core image `ghcr.io/goldvalleysolutions/core-bot` is private on GHCR. Create a GitHub
token with `read:packages`, then build this bot `FROM ghcr.io/goldvalleysolutions/core-bot:${CORE}`
(`CORE=0.2`, never `latest`) from the repo root (Docker or Colima, arm64 or amd64):

```bash
echo YOUR_PAT | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin

git clone git@github.com:goldvalleysolutions/gvs-inbox-assistant-bot.git
cd gvs-inbox-assistant-bot
docker build -f bot/Dockerfile --build-arg CORE=0.2 -t inbox-assistant-bot:dev .
docker run -d -p 8080:8080 -v inbox-assistant-data:/data inbox-assistant-bot:dev
```

The Dockerfile copies `bot/` to `/bot/` on top of the pinned core; no RUN steps.

Open <http://localhost:8080>. Every page redirects to **`/setup`** until you finish
it. Create the box-admin login, leave the LLM on **stub** (no key, $0), enter SMTP
only if you want `email.send`, then run the self-test.
`curl -f http://localhost:8080/health` works before and after setup.

There is no published image for this bot yet; build it locally as above.

### Try it (stub, CI)

Do these on the running image. CI runs the walkthrough against a fake SMTP
server (never a real mailbox) on amd64 and arm64. Stub LLM only — no provider keys.

1. **`/setup`** — stub model, no LLM key. SMTP host/port/user/password/from if
   you want mail (CI points this at a local fake SMTP).
2. **Clock** — ask the time. `clock.now` runs and is logged.
3. **Triage** — paste a customer email. The `triage` skill labels it and drafts
   a reply. There is no IMAP or POP.
4. **Notes** — save a one-line follow-up with `notes`.
5. **Email** — send the draft to the allowlisted admin address. Fake SMTP
   receives it; the activity log records `email.send`.
6. **Web browse blocked** — ask it to search the web. The call is refused and
   logged `blocked` / `not_allowed`.
7. **Box admin 404** — as box admin, `/gvs/role`, `/gvs/skills`, `/gvs/memory`
   and `/gvs/activity` are 404.
8. **MCP** — in box admin, turn MCP on in **read only**, issue a token. An MCP
   client at `/mcp` can `ask` and `tools/list` (no `email.send`). Switch to
   **write with approval**, request a send, approve it. Fake SMTP receives the
   mail. See [docs/mcp.md](../../docs/mcp.md).

## What it can do

- Triage pasted email (urgent / wait / fyi / no-reply) and draft a reply
- Tell the time (`clock.now`) and keep short follow-ups (`notes`)
- Send the draft (`email.send`) after SMTP is set on `/setup`, only to the admin allowlist
- Remember facts across a container restart
- Refuse web browsing, IMAP/POP mailbox fetch, and any tool not on `tools_allowed`

## Prerequisites

| Mode | What you need |
|---|---|
| Stub (default, CI, this README) | Docker. No LLM key. $0. |
| Live | A key from Anthropic, OpenAI, OpenRouter, or xAI, entered on `/setup` or in admin. Never committed. |
| Email | SMTP host/port (and user/password/from if the server needs them). CI uses a fake server. No IMAP or POP. |

Default spend cap is **$25/month**. At the cap the box falls back to stub.

## Estimated monthly cost

Cost ≈ (chats per day × days × turns per chat × $ per turn). Inbox Assistant's
profile in `bot.yaml` is **10 chats/day** and **4 turns/chat**. On the stub
model that is **$0**. On a small live model, treat $0.01–0.03 per turn as a
planning range; the box stops live calls at the **$25** cap.

| How often | How chatty | Est. / month (live) | Notes |
|---|---|---|---|
| Light (2 chats/day) | Short (2 turns) | $0–2 | Well under the cap |
| Typical (10 chats/day) | Inbox default (4 turns) | $5–15 | The `cost:` profile |
| Heavy (30 chats/day) | Long (8 turns) | up to **$25** | Cap, then stub |
| Stub only | any | **$0** | CI and first-boot default |

Keys and SMTP passwords live encrypted in `/data/bot.db`. They are never in the
image, the repo, or CI.

## Admin

| | Box admin (you create on `/setup`) | GVS operator (`gvs-root` token) |
|---|---|---|
| LLM provider, model, API key | ✅ | ✅ |
| SMTP, allowlist, spend cap, theme, MCP | ✅ | ✅ |
| Role, skills, memory, activity, users | ❌ 404 | ✅ |

There is no root password and no self-hoster root option. A
**Powered by Gold Valley Solutions** footer is on every page and cannot be hidden.

## Configuration

| Item | Where | Notes |
|---|---|---|
| Manifest | `bot/bot.yaml` | `make lint-bot BOT=<this repo>/bot (in gvs-core-bot)` |
| Role / skills | `role.md`, `skills/triage/SKILL.md` | Seeded into `bot.db` on first boot |
| Tools | `tools/` | Empty; built-ins only (`clock.now`, `notes`, `email.send`) |
| Theme | `theme.yaml` | GVS gold/white/Inter defaults |
| Data | `/data/bot.db` + `/data/bot.key` | One SQLite DB; key is 0600 |
| Port | `8080` | Non-root user in the image |

## Updates and backups

Rebuild `inbox-assistant-bot:dev` after `git pull` (the `docker build` above).
Unedited role/skill text updates from the image; text the GVS operator edited is
kept. Back up `bot.db` and `bot.key` **separately**. Losing the key means
re-entering secrets; losing only the DB means a fresh `/setup`. Delete the
volume to start over.

## FAQ

**Working with health records?** When you run a project yourself, you choose an
AI provider and host that fit your compliance needs. Our hosting and builds
don't process patient health information.

**Can it browse the web?** No. That is not on `tools_allowed` and a call is
refused and logged.

**Does it read my mailbox?** No. There is no IMAP or POP. Paste or type the
message you want triaged.

**Does CI send real email?** No. Tests and the image job use a local fake SMTP
server.

## Help and paid services

Gold Valley Solutions offers paid **setup, configuration, training and hosting**.
See the [box pricing page](https://www.goldvalleysolutions.com/).

## License

Apache License 2.0. See the repository `LICENSE` and `NOTICE`.
© 2026 Gold Valley Solutions LLC.

## End-to-end tests (Playwright)

`tests/e2e/` starts the bot on core from source (pinned to gvs-core-bot `f597d3d`) with
uvicorn, a temp `/data` and the stub model, then drives it in Chromium at desktop
(1280x800) and mobile (390x844) sizes. `verify-local.sh` runs it through
`.verify-local.env`, and it must pass before merge.

```bash
git clone https://github.com/goldvalleysolutions/gvs-core-bot.git ../gvs-core-bot
git -C ../gvs-core-bot checkout f597d3d
pip install -r ../gvs-core-bot/requirements.txt -r tests/e2e/requirements.txt
python -m playwright install chromium
GVS_CORE_DIR=../gvs-core-bot python -m pytest tests/e2e -q
```

When a test fails, a screenshot and a trace go to `tests/e2e/artifacts/` (gitignored).
Open the trace with `python -m playwright show-trace <file>.trace.zip`.
