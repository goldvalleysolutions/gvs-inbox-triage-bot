"""This bot's pages and HTTP setup for the shared e2e tests (test_access_policy.py)."""

BOT_PAGES: list[str] = []  # Brief page /r/inbox-triage/brief is admin-only; chat (/) follows the policy
HTTP_SETUP = {"mail": True}
