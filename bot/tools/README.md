Custom tools for this box (0–3 `*.py` files), registered through `core.sdk`.

Inbox Assistant ships no role tools. The allowlist is the core built-ins
`clock.now`, `notes`, and `email.send` (disabled until SMTP_* are set on
`/setup`). The owner pastes email text; there is no IMAP or POP connector.
Web browsing is not allowed and is refused + logged as `blocked`.
