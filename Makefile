.PHONY: help install lint fmt test tf-init tf-plan tf-apply tf-destroy up down clean
.DEFAULT_GOAL := help

TF := terraform -chdir=infra

help:  ## Show this help
	grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install:  ## Install dev dependencies
	python3 -m venv .venv
	.venv/bin/pip install --quiet --upgrade pip
	.venv/bin/pip install -e ".[dev]"

fmt:  ## Format Python and Terraform
	.venv/bin/ruff check --fix src tests
	.venv/bin/black src tests
	$(TF) fmt -recursive

lint:  ## Lint without modifying files
	.venv/bin/ruff check src tests
	.venv/bin/black --check src tests
	$(TF) fmt -check -recursive

test:  ## Run unit tests (no AWS calls - moto mocks everything)
	.venv/bin/pytest -q

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
