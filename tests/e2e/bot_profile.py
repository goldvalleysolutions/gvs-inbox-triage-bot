"""This bot's pages and HTTP setup for the shared e2e tests (test_access_policy.py)."""

BOT_PAGES: list[str] = []  # no add-on routes; chat (/) follows the access policy
HTTP_SETUP = {"smtp": True}
