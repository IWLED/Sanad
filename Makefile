.PHONY: help up down test lint eval fmt clean backup

help:
	@echo "Sanad (Personal AI Secretary) Commands:"
	@echo "  make test      Run server unit, security, and contract tests"
	@echo "  make lint      Run linting and type checking (ruff, mypy)"
	@echo "  make fmt       Format code (ruff format)"
	@echo "  make eval      Run AI model evaluations"
	@echo "  make up        Start server services via Docker Compose"
	@echo "  make down      Stop server services"

test:
	cd server && uv run pytest

lint:
	cd server && uv run ruff check .
	cd server && uv run mypy app

fmt:
	cd server && uv run ruff format .
	cd server && uv run ruff check --fix .

eval:
	cd server && uv run python eval/run_eval.py

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
