.PHONY: up down migrate test lint eval clean web web-build

up:
	docker compose up -d

migrate:
	alembic upgrade head

down:
	docker compose down

test:
	python -m pytest -q

lint:
	python -m ruff check .

# Verifier first (no DB or LLM needed), then the corpus-based runs, then refresh README/RESULTS.
eval:
	python -m packages.evaluation.runner
	python -m packages.evaluation.run_verifier
	python -m packages.evaluation.run_ablation
	python -m packages.evaluation.run_agent
	python scripts/render_results.py

clean:
	rm -rf .pytest_cache .ruff_cache __pycache__

web:
	cd apps/web && npm install && npm run dev

web-build:
	cd apps/web && npm install && npm run build && npm test
