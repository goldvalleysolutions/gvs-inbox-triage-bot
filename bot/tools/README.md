Custom tools for this bot (0–3 `*.py` files), registered through
`gvs_bot_core.tools`.

Inbox Assistant ships no role tools. The allowlist is the core built-ins
`clock.now`, `notes`, and `email.send` (disabled until SMTP_* are set on
`/setup`). The owner pastes email text; there is no IMAP or POP connector.
Web browsing is not allowed and is refused + logged as `blocked`.
