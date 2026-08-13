.PHONY: help venv install preflight lint fmt test tf-init tf-plan tf-apply tf-destroy up down clean
.DEFAULT_GOAL := help

TF     := terraform -chdir=infra
PY     := python3
VENV   := .venv
BIN    := $(VENV)/bin

help:  ## Show this help
	grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

$(BIN)/activate:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install --quiet --upgrade pip

venv: $(BIN)/activate  ## Create the virtualenv

install: venv  ## Install dev dependencies into .venv
	$(BIN)/pip install -e ".[dev]"
	echo ""
	echo "  Installed. Activate with:  source $(BIN)/activate"

preflight:  ## Verify all Step 1 preconditions
	./scripts/preflight.sh

fmt: venv  ## Format Python and Terraform
	$(BIN)/ruff check --fix src tests
	$(BIN)/black src tests
	$(TF) fmt -recursive

lint: venv  ## Lint without modifying files
	$(BIN)/ruff check src tests
	$(BIN)/black --check src tests
	$(TF) fmt -check -recursive

test: venv  ## Run unit tests (no AWS calls - moto mocks everything)
	$(BIN)/pytest -q

tf-init:  ## Initialize Terraform against the S3 backend
	$(TF) init -backend-config=backend.hcl

tf-plan:  ## Show planned infrastructure changes
	$(TF) plan

tf-apply:  ## Apply infrastructure changes
	$(TF) apply

tf-destroy:  ## Tear everything down. Run this when you stop working.
	$(TF) destroy

up:  ## Start local Redpanda (used from day 2 onward)
	docker compose -f docker/docker-compose.yml up -d

down:  ## Stop local containers
	docker compose -f docker/docker-compose.yml down -v

clean:  ## Remove caches and build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache dist build *.egg-info

distclean: clean  ## Also remove the virtualenv
	rm -rf $(VENV)
