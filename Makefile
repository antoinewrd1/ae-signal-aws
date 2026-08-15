.PHONY: help venv install preflight lint fmt test topic produce consume offsets transform-local glue-run enrich-local enrich-metrics cache-clear eval run-pipeline pipeline-status tf-init tf-plan tf-apply tf-destroy up down clean
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

up:  ## Start local Redpanda + console (http://localhost:8080)
	docker compose -f docker/docker-compose.yml up -d
	@echo "  Waiting for broker..."
	@sleep 8
	@docker exec ae-signal-redpanda rpk cluster health || true

topic:  ## Create the drug-event topic (3 partitions)
	docker exec ae-signal-redpanda rpk topic create ae-signal.drug-event.raw -p 3 -r 1 || true
	docker exec ae-signal-redpanda rpk topic list

produce:  ## Replay bronze records onto the topic
	$(BIN)/python -m src.stream produce --rate 200 --limit 500

consume:  ## Consume the topic into bronze-stream/
	$(BIN)/python -m src.stream consume --max-records 100 --max-batches 5

transform-local:  ## Run the Spark transform against ./data (no AWS, no cost)
	$(BIN)/python -m src.transform.job --bronze_path './data/bronze/drug_event/*/*.json.gz' --silver_path ./data/silver --gold_path ./data/gold

glue-run:  ## Trigger the deployed Glue job (BILLS ~10 min minimum)
	aws glue start-job-run --job-name $$(terraform -chdir=infra output -raw glue_job_name)

enrich-local:  ## Bedrock enrichment on 20 silver records (COSTS ~$0.01)
	$(BIN)/python -m src.enrich --silver ./data/silver --limit 20

enrich-metrics:  ## Show the latest enrichment metrics
	@cat $$(ls -t data/gold/_metrics/assessments/*/*.json | head -1)

cache-clear:  ## Drop the Bedrock response cache
	rm -rf .cache/bedrock && echo "cache cleared"

eval:  ## Score enrichment output against ground truth
	$(BIN)/python -m src.eval --input ./data/gold/assessments --out ./docs/eval.md

run-pipeline:  ## Trigger the Step Functions pipeline (BILLS glue + bedrock)
	aws stepfunctions start-execution --state-machine-arn $$(terraform -chdir=infra output -raw state_machine_arn) --input '{"limit":20}'

pipeline-status:  ## Last pipeline execution
	@aws stepfunctions list-executions --state-machine-arn $$(terraform -chdir=infra output -raw state_machine_arn) --max-items 1 --query 'executions[0].[status,startDate,name]' --output table

offsets:  ## Show consumer group lag
	docker exec ae-signal-redpanda rpk group describe ae-signal-bronze-writer

down:  ## Stop local containers
	docker compose -f docker/docker-compose.yml down -v

clean:  ## Remove caches and build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache dist build *.egg-info

distclean: clean  ## Also remove the virtualenv
	rm -rf $(VENV)
