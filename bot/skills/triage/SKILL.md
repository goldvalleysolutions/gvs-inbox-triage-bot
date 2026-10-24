---
name: triage
description: Triage pasted email and draft a reply the owner can send.
---

# Inbox triage and reply

The owner pastes the message. Do not ask for IMAP, POP, or mailbox passwords.

1. **Read** — Restate who wrote, what they want, and any date or amount in one
   short line. Use `clock.now` if "today" or a deadline needs a timestamp.
2. **Triage** — Pick one label:
   - **urgent** — money, legal, a customer waiting, or a same-day deadline
   - **wait** — needs a fact, a file, or the owner to decide
   - **fyi** — no reply needed; file it
   - **no-reply** — spam, automated receipt, or already handled
3. **Draft** — For urgent and wait, write a reply the owner can send as-is:
   greeting, one-paragraph answer, one clear next step, sign-off. Keep their
   voice (plain, not salesy). Offer a shorter version if they ask.
4. **Notes** — Save a one-line follow-up with `notes` when something is still
   open after the reply.
5. **Send** — Only if the owner asks to send, and only with `email.send` to an
   allowlisted address after SMTP is set on `/setup`. Never invent a To: that
   is not on the allowlist. Never fetch mail from a server.
