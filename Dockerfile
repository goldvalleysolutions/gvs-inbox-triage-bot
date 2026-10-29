# syntax=docker/dockerfile:1
# Inbox Assistant Bot: pinned bot-core + this bot overlay.
# CORE is X.Y (never latest) and must match `core:` in bot.yaml.
# Copy-only: this bot has no extra Python deps, so no RUN that changes core.
ARG CORE=0.2
FROM ghcr.io/goldvalleysolutions/bot-core:${CORE}
ARG CORE=0.2
ARG IMAGE_TAG=ghcr.io/goldvalleysolutions/inbox-assistant-bot:dev
LABEL org.opencontainers.image.title="Inbox Assistant Bot" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.base.name="bot-core:${CORE}" \
      org.opencontainers.image.ref.name="ghcr.io/goldvalleysolutions/inbox-assistant-bot"
ENV GVS_IMAGE_TAG=${IMAGE_TAG}
COPY bot/ /bot/
