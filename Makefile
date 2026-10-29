CORE ?= 0.2
CORE_IMAGE ?= ghcr.io/goldvalleysolutions/bot-core:$(CORE)
IMAGE ?= ghcr.io/goldvalleysolutions/inbox-assistant-bot:dev
DOCKERFILE ?= Dockerfile

.PHONY: build lint-bot steps

build:
	docker build --build-arg CORE=$(CORE) -f $(DOCKERFILE) -t $(IMAGE) .

lint-bot:
	docker run --rm -v "$(CURDIR)/bot:/bot:ro" $(CORE_IMAGE) python -m core.config.lint /bot

steps:
	scripts/inbox-assistant-steps.sh "$(IMAGE)"
