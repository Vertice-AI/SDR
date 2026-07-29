.PHONY: setup dev worker test test-conv lint fix migrate upgrade seed

PYTHON_VERSION := 3.12

setup:
	uv venv --python $(PYTHON_VERSION)
	uv sync
	docker compose up -d --wait
	uv run alembic upgrade head

dev:
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker:
	uv run arq app.workers.worker.WorkerSettings

test:
	uv run pytest

test-conv:
	uv run pytest tests/conversations -m "not live"

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy app

fix:
	uv run ruff format .
	uv run ruff check --fix .

migrate:
	uv run alembic revision --autogenerate -m "$(m)"

upgrade:
	uv run alembic upgrade head

seed:
	uv run python -m app.scripts.seed
