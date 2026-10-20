.PHONY: help install dev up down build logs shell lint format typecheck pre-commit clean test test-unit test-integration test-cov test-realmongo sdk-sync sdk-test docker-smoke

help:
	@echo "Available commands:"
	@echo "  make install          - Install dependencies"
	@echo "  make dev              - Run development server locally"
	@echo "  make up               - Start docker-compose services"
	@echo "  make down             - Stop docker-compose services"
	@echo "  make build            - Build docker images"
	@echo "  make logs             - View docker-compose logs"
	@echo "  make shell            - Open shell in api container"
	@echo "  make lint             - Run ruff linter"
	@echo "  make format           - Format code with black and ruff"
	@echo "  make typecheck        - Run mypy type checker"
	@echo "  make pre-commit       - Run pre-commit hooks"
	@echo "  make clean            - Remove cache files"
	@echo "  make test             - Run all tests"
	@echo "  make test-unit        - Run unit tests only"
	@echo "  make test-integration - Run integration tests only"
	@echo "  make test-cov         - Run tests with coverage report"
	@echo "  make test-realmongo   - Run the real-MongoDB transaction tests (needs Docker)"
	@echo "  make sdk-sync         - Regenerate the SDK's vendored decision core"
	@echo "  make docker-smoke     - Build the image and check it serves /health"
	@echo "  make sdk-test         - Run the Python SDK checks (needs poetry install in sdks/python)"

install:
	poetry install

dev:
	poetry run uvicorn osiki.main:app --reload --host 0.0.0.0 --port 8000

up:
	docker-compose up -d

down:
	docker-compose down

build:
	docker-compose build

logs:
	docker-compose logs -f

shell:
	docker-compose exec api /bin/bash

lint:
	poetry run ruff check .

format:
	poetry run black .
	poetry run ruff check --fix .

typecheck:
	poetry run mypy .

pre-commit:
	poetry run pre-commit run --all-files

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true

test:
	poetry run pytest

test-unit:
	poetry run pytest tests/unit

test-integration:
	poetry run pytest tests/integration

test-cov:
	poetry run pytest --cov=osiki --cov-report=term-missing

test-realmongo:
	bash scripts/realmongo-test.sh

sdk-sync:
	python scripts/sync_sdk_decision.py

sdk-test:
	python scripts/sync_sdk_decision.py --check
	cd sdks/python && poetry run black --check . && poetry run ruff check . && poetry run mypy src && poetry run pytest --cov=osiki_sdk

docker-smoke:
	bash scripts/docker-smoke.sh
