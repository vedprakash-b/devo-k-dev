# Devo-K-Dev developer commands. Run `make help` to list them.
# Everything goes through uv, so the right Python and dependencies are always used.

COMPOSE := docker compose --env-file .env -f deploy/docker-compose.yml

.DEFAULT_GOAL := help
.PHONY: help setup env up down reset logs ps doctor smoke fmt lint typecheck test test-integration check demo models

help: ## List the commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

setup: env ## Install Python 3.12, dependencies and git hooks
	uv python install 3.12
	uv sync
	uv run pre-commit install

env: ## Create .env from .env.example if it does not exist yet
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example")

up: env ## Start Temporal, PostgreSQL + pgvector and Redis, and wait until healthy
	$(COMPOSE) up -d --wait

down: ## Stop the stack (data in PostgreSQL and Redis is kept)
	$(COMPOSE) down

reset: ## Stop the stack and DELETE its data volumes
	$(COMPOSE) down -v

logs: ## Follow the stack's logs
	$(COMPOSE) logs -f

ps: ## Show the stack's containers
	$(COMPOSE) ps

doctor: ## Check that everything Devo-K-Dev needs is reachable
	uv run devokdev doctor

smoke: ## Run a tiny Temporal workflow end to end
	uv run devokdev smoke

demo: ## Watch the router hand a conversation over after a 429 (offline, no keys)
	uv run devokdev models demo

models: ## List the model registry and which models your keys unlock
	uv run devokdev models list

fmt: ## Format and auto-fix
	uv run ruff format .
	uv run ruff check --fix .

lint: ## Lint and check formatting
	uv run ruff check .
	uv run ruff format --check .

typecheck: ## mypy in strict mode
	uv run mypy

test: ## Unit tests with coverage
	uv run pytest --cov --cov-report=term-missing

test-integration: ## Integration tests against the running stack (make up first)
	uv run pytest --run-integration -m integration

check: lint typecheck test ## Everything CI runs on every pull request
