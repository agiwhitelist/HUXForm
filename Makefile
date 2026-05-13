.PHONY: help setup start doctor clean build docker

help:
	@echo "HUXForm — the interface takes the shape of the task"
	@echo ""
	@echo "  make setup    install backend + frontend, write .env"
	@echo "  make start    launch api (:8001) and web (:5173)"
	@echo "  make doctor   check prerequisites"
	@echo "  make clean    remove .venv, node_modules, data"
	@echo "  make build    production build (web)"
	@echo "  make docker   docker compose up --build"
	@echo ""

setup:
	@./bin/huxform setup

start:
	@./bin/huxform start

doctor:
	@./bin/huxform doctor

clean:
	@./bin/huxform clean

build:
	cd apps/web && npm run build

docker:
	docker compose up --build
