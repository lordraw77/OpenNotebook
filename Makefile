# OpenNotebook — developer and operator entry points. Run `make help`.
SHELL := /bin/bash
.DEFAULT_GOAL := help

VERSION  ?= $(shell cat VERSION 2>/dev/null || echo dev)
REGISTRY ?= lordraw
ENV_FILE ?= .env
OPENNOTEBOOK_ENV_FILE := $(abspath $(ENV_FILE))
export VERSION REGISTRY OPENNOTEBOOK_ENV_FILE

COMPOSE := docker compose --env-file $(ENV_FILE) -f deploy/compose/docker-compose.yml

.PHONY: help secrets build up down restart logs ps migrate bootstrap doctor run test test/backend test/frontend \
        lint fmt check-no-models bundle release docker/build docker/run docker/stop clean

help: ## Show this help
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_\/-]+:.*## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

secrets: ## Create .env from .env.example if missing and fill empty internal secrets (idempotent)
	@scripts/gen-secrets.sh $(ENV_FILE)

build: ## Build all OpenNotebook images (web, api, worker)
	$(COMPOSE) build

up: ## Start the stack (profiles from COMPOSE_PROFILES in .env)
	$(COMPOSE) up -d
	@echo "OpenNotebook: http://localhost:$$(grep -E '^WEB_PORT=' $(ENV_FILE) | cut -d= -f2 | grep . || echo 8080)"

down: ## Stop the stack (volumes are kept)
	$(COMPOSE) down

restart: ## Restart application services
	$(COMPOSE) restart api worker web

logs: ## Follow logs of all services
	$(COMPOSE) logs -f --tail=200

ps: ## Service status and health
	$(COMPOSE) ps

migrate: ## Apply database migrations
	$(COMPOSE) run --rm migrate "opennotebook migrate"

bootstrap: ## Re-run first-start initialization (admin, bucket, providers from .env, MODEL_* defaults)
	$(COMPOSE) run --rm migrate "opennotebook bootstrap"

doctor: ## Check connectivity to every internal service and configured provider
	$(COMPOSE) exec api opennotebook doctor

run: up ## Alias of `up`

test: test/backend test/frontend ## Run all test suites

test/backend: ## Backend tests (disposable PostgreSQL + Redis containers)
	@scripts/test-backend.sh

test/frontend: ## Frontend unit tests
	cd frontend && npm ci --no-audit --no-fund && npm test

lint: ## Lint backend (ruff) and frontend (prettier)
	cd backend && uv run ruff check src tests && uv run ruff format --check src tests
	cd frontend && npm run lint

fmt: ## Format backend and frontend code
	cd backend && uv run ruff format src tests && uv run ruff check --fix src tests
	cd frontend && npx prettier --write "src/**/*.{ts,html,scss}"

check-no-models: ## Verify that images contain no model weights or ML runtimes
	@scripts/check-no-models.sh $(REGISTRY)/opennotebook-api:$(VERSION) $(REGISTRY)/opennotebook-worker:$(VERSION)

bundle: build check-no-models ## Create a release tarball (images + compose + .env.example + install.sh)
	@scripts/bundle.sh $(VERSION) $(REGISTRY)

release: build check-no-models ## Push images (VERSION and latest): make release REGISTRY=<namespace>
	@test "$(VERSION)" != "dev" || (echo "Set VERSION=x.y.z" && exit 1)
	for img in web api worker; do \
	  docker tag $(REGISTRY)/opennotebook-$$img:$(VERSION) $(REGISTRY)/opennotebook-$$img:latest && \
	  docker push $(REGISTRY)/opennotebook-$$img:$(VERSION) && docker push $(REGISTRY)/opennotebook-$$img:latest; \
	done

backup: ## Back up database, files, vector index and .env into ./backups (scripts/backup.sh)
	@COMPOSE="$(COMPOSE)" scripts/backup.sh

restore: ## Restore a backup: make restore BACKUP=backups/opennotebook-<stamp> (replaces all data)
	@test -n "$(BACKUP)" || (echo "Set BACKUP=backups/opennotebook-<stamp>" && exit 1)
	@COMPOSE="$(COMPOSE)" scripts/restore.sh $(BACKUP)

sync-deploy: ## Render observability config into deploy/production/docker-compose.yml
	@python3 scripts/sync_observability.py

hub-publish: ## Build, check, push to Docker Hub and update the repository overviews (scripts/publish-dockerhub.sh)
	@scripts/publish-dockerhub.sh $(VERSION) $(REGISTRY)

docker/build: build ## Alias of `build`
docker/run: up ## Alias of `up`
docker/stop: down ## Alias of `down`

clean: ## Stop the stack and DELETE all volumes (data loss)
	@read -p "This deletes all OpenNotebook data volumes. Type 'yes' to continue: " ok && [ "$$ok" = yes ]
	$(COMPOSE) down -v
