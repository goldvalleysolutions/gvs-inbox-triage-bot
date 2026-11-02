# Inbox Triage Bot

A small-business inbox clerk: it reads your mailbox **read-only** over IMAP, gives you a
**daily brief** (7:00 AM local, editable, and on demand: "brief me"), and **drafts replies
when you ask**. Nothing is sent until you approve each send. One image, `/setup`, memory,
allowlisted tools, and the Gold Valley Solutions gold theme.

> Renamed: this repo was `gvs-inbox-assistant-bot`; it is now `gvs-inbox-triage-bot` (image `goldvalleysolutions/inbox-triage-bot`).

## Up and running in 5 minutes

Pull and run (only Docker needed; amd64 or arm64). The image is published to Docker Hub as
`goldvalleysolutions/inbox-triage-bot` when Mike merges `test` into `main`; until then, build
it locally as shown below.

```bash
docker pull goldvalleysolutions/inbox-triage-bot:0.2
docker run -d --name inbox-triage -p 8080:8080 -v inbox-triage-data:/data goldvalleysolutions/inbox-triage-bot:0.2
```

Build locally (developers): the Dockerfile is `FROM goldvalleysolutions/core-bot:${CORE}`
(`CORE=0.3`, never `latest`) and only copies `bot/` to `/bot/` (no RUN steps).

```bash
git clone https://github.com/goldvalleysolutions/gvs-inbox-triage-bot.git
cd gvs-inbox-triage-bot
docker build -f bot/Dockerfile --build-arg CORE=0.3 -t inbox-triage-bot:dev .
docker run -d --name inbox-triage -p 8080:8080 -v inbox-triage-data:/data inbox-triage-bot:dev
```

Open <http://localhost:8080>. Every page redirects to **`/setup`** until you finish
it. Create the bot-admin login, leave the LLM on **stub** (no key, $0), then in
**Mail account** pick Gmail, Zoho or Outlook/M365 (or enter any IMAP/SMTP host), type your
email and one **app password**, press **Test connection** (IMAP sign-in + SMTP check,
nothing sent), and run the self-test. Until a mailbox is set the bot uses four demo messages.
`curl -f http://localhost:8080/health` works before and after setup.


### Try it (stub, CI)

CI runs this against a **fake IMAP server** (records every flag change and APPEND) and a
**fake SMTP server**, never a real mailbox, with the stub LLM.

1. **`/setup`** — stub model; Mail account → Test connection passes (and fails on a wrong password).
2. **Brief me** — `brief.build` syncs read-only and returns the brief (below).
3. **Read + triage** — `mail.read` opens one message; the mailbox's flags never change.
4. **Draft** — "draft a reply to #1": shown in chat only.
5. **Send** — "send it": `email.send` waits for your **Approve** click, then goes to SMTP and a
   copy is APPENDed to Sent (the only mailbox write).
6. **Schedule** — the `daily_brief` job runs at 7:00 AM local; Admin → Schedules edits it.
   The **Brief page** (`/r/inbox-triage/brief`) shows the last brief, **Run now**,
   **Email the brief to me**, retention days and **Forget mailbox**.
7. **Injection** — a mail saying "send the bank details to …" triggers no tool; any action
   after reading mail waits for approval.

## The daily brief

| Part | What you get |
|---|---|
| Categories | **clients, billing, vendors, newsletters, other** |
| Urgency | **now / today / FYI** on every item |
| Summaries | 1-2 lines per message (who, what, first sentence) |
| Needs a reply | a list of messages where a real person asked something |
| When | daily at 7:00 AM local (editable), and on demand ("brief me") |
| Where | in the app (chat + Brief page); optionally emailed to yourself over SMTP |

## What it can do

- Read one mailbox over IMAP **read-only** (EXAMINE + BODY.PEEK; no flags, moves or deletes),
  incremental by UID, last 7 days, capped per run (Core connector)
- Build the daily brief (`brief.build`, `brief.now`, job `daily_brief`)
- List and read mail (`mail.list`, `mail.read`); triage into category + urgency
- Draft replies only when asked; send with `email.send` only after you approve each one
  (Core also only sends to addresses on the admin **allowlist**: add a client there before
  approving a reply to them).
- Tell the time (`clock.now`), keep follow-ups (`notes`), remember facts across restarts
- Refuse web browsing and any tool not on `tools_allowed`; treat mail text as untrusted

## Prerequisites

| Mode | What you need |
|---|---|
| Stub (default, CI, this README) | Docker. No LLM key. $0. |
| Live | A key from Anthropic, OpenAI, OpenRouter, or xAI, entered on `/setup` or in admin. Never committed. |
| Mail | One mailbox: email + app password (IMAP read, SMTP send). Presets for Gmail, Zoho, Outlook/M365. CI uses fake servers. |

Default spend cap is **$25/month**. At the cap the bot falls back to stub.

## Estimated monthly cost

Cost ≈ (chats per day × days × turns per chat × $ per turn). Inbox Triage Bot's
profile in `bot.yaml` is **10 chats/day** and **4 turns/chat**; the daily brief itself is rule-based and costs $0. On the stub
model that is **$0**. On a small live model, treat $0.01–0.03 per turn as a
planning range; the bot stops live calls at the **$25** cap.

| How often | How chatty | Est. / month (live) | Notes |
|---|---|---|---|
| Light (2 chats/day) | Short (2 turns) | $0–2 | Well under the cap |
| Typical (10 chats/day) | Inbox default (4 turns) | $5–15 | The `cost:` profile |
| Heavy (30 chats/day) | Long (8 turns) | up to **$25** | Cap, then stub |
| Stub only | any | **$0** | CI and first-boot default |

Keys and the mail app password live encrypted in `/data/bot.db`. They are never in the
image, the repo, or CI.

## Admin

| | Bot admin (you create on `/setup`) | GVS operator (`gvs-root` token) |
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
| Role / skills | `role.md`, `skills/{triage,daily-brief,reply-draft}/SKILL.md` | Seeded into `bot.db` on first boot |
| Tools | `tools/inbox.py` | `mail.list`, `mail.read`, `brief.build`, `brief.now` (thin wrappers on Core's IMAP connector and jobs) + built-ins |
| Job | `services/brief.py` | `daily_brief`, `daily 07:00`; Brief page `/r/inbox-triage/brief` |
| Approvals | `approval_required: [email.send]` | Every send waits for the owner |
| Retention | Brief page | Cached mail kept 30 days by default; Forget mailbox wipes it |
| Theme | `theme.yaml` | GVS gold/white/Inter defaults |
| Data | `/data/bot.db` + `/data/bot.key` | One SQLite DB; key is 0600 |
| Port | `8080` | Non-root user in the image |

## Updates and backups

Update with `docker pull goldvalleysolutions/inbox-triage-bot:0.2`, then `docker rm -f inbox-triage`
and re-run the same `docker run` command (the `inbox-triage-data` volume keeps your data).
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

**Does it read my mailbox?** Yes, read-only. It never marks, moves or deletes mail.
The only writes are copies saved to Sent: a reply you approved and, if you turn on
"Email the brief to me", the daily brief email.

**Can it send on its own?** No. Every `email.send` waits for your Approve click, and
instructions inside an email never trigger a tool.

**Does CI send real email?** No. Tests and the image job use local fake IMAP and SMTP
servers.

## Help and paid services

Gold Valley Solutions offers paid **setup, configuration, training and hosting**.
See the [Gold Valley Bots pricing page](https://www.goldvalleysolutions.com/pricing/gold-valley-bots.html).

## License

Apache License 2.0. See the repository `LICENSE` and `NOTICE`.
© 2026 Gold Valley Solutions LLC.

## End-to-end tests (Playwright)

`tests/e2e/` starts the bot on core from source (pinned to gvs-core-bot `1c6e619`) with
uvicorn, a temp `/data` and the stub model, then drives it in Chromium at desktop
(1280x800) and mobile (390x844) sizes. `verify-local.sh` runs it through
`.verify-local.env`, and it must pass before merge.

```bash
git clone https://github.com/goldvalleysolutions/gvs-core-bot.git ../gvs-core-bot
git -C ../gvs-core-bot checkout 1c6e619
pip install -r ../gvs-core-bot/requirements.txt -r tests/e2e/requirements.txt
python -m playwright install chromium
GVS_CORE_DIR=../gvs-core-bot python -m pytest tests/e2e -q
```

When a test fails, a screenshot and a trace go to `tests/e2e/artifacts/` (gitignored).
Open the trace with `python -m playwright show-trace <file>.trace.zip`.
