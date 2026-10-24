# syntax=docker/dockerfile:1
# Inbox Assistant in a Box: generated role image = a pinned core base + this box folder.
# Copy-only: no RUN that changes core (B1, AC-14). Same layering as Hello.
#   Local:   make build tags gvs-box-base:<X.Y> first. Default
#            CORE_IMAGE=gvs-box-base:${CORE} so FROM is the pin (never latest).
#   Release: docker-bake.hcl overrides CORE_IMAGE to the bare name `gvs-box-base`
#            and feeds the freshly built `base` target through that named context.
# CORE pins the core as X.Y (never latest); it must equal `core:` in box.yaml.
ARG CORE=0.1
ARG CORE_IMAGE=gvs-box-base:${CORE}
FROM ${CORE_IMAGE}
ARG CORE=0.1
ARG CORE_IMAGE
ARG IMAGE_TAG=inbox-assistant-in-a-box:dev
LABEL org.opencontainers.image.title="Inbox Assistant in a Box" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.base.name="gvs-box-base:${CORE}"
ENV GVS_IMAGE_TAG=${IMAGE_TAG}
COPY boxes/inbox-assistant/ /box/
