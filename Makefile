# Single entrypoint for common tasks. Wraps the per-OS .sh/.bat scripts so
# there is one place to look. Run `make help` for the list.
PY := KG_backend/.venv/bin/python

.DEFAULT_GOAL := help
.PHONY: help setup dev backend frontend test fixture migrate build up down logs rag lint

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Install backend + frontend deps (check_prereqs)
	./check_prereqs.sh

dev: ## Run backend + frontend locally (runserver + next dev)
	./run_server.sh

backend: ## Run only the Django backend (dev)
	cd KG_backend && .venv/bin/python manage.py runserver

frontend: ## Run only the Next.js frontend (dev)
	cd kg_frontend && npm run dev

test: ## Run the backend test suite
	cd KG_backend && .venv/bin/python manage.py test

migrate: ## Apply database migrations
	cd KG_backend && .venv/bin/python manage.py migrate

fixture: ## Regenerate the Car fixture from the current DB
	cd KG_backend && .venv/bin/python manage.py dumpdata api.Car --indent 2 -o api/fixtures/cars.json

build: ## Build both Docker images
	docker compose build

up: ## Start the full prod-like stack (Postgres + backend + frontend)
	docker compose up --build

down: ## Stop the stack
	docker compose down

logs: ## Tail compose logs
	docker compose logs -f

rag: ## Build the offline RAG / diagnostic index
	./run_rag_build.sh

lint: ## Lint the frontend
	cd kg_frontend && npm run lint
