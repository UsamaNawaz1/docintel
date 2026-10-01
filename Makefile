.PHONY: setup lint format typecheck test run worker beat migrate seed

setup:
	uv sync --all-groups
	uv run pre-commit install || true

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

typecheck:
	uv run mypy

test:
	uv run pytest

run:
	uv run python manage.py runserver

worker:
	uv run celery -A docintel.config.celery worker -Q default,ocr -l info

beat:
	uv run celery -A docintel.config.celery beat -l info

migrate:
	uv run python manage.py migrate

seed:
	uv run python manage.py seed_demo
