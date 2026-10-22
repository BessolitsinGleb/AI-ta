.PHONY: install dev test test-back test-front eval eval-demo deck docker lan publish-site fuel-data

install:
	python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

dev:
	.venv/bin/uvicorn app.main:app --app-dir backend --reload --port 8000

test: test-back test-front

test-back:
	cd backend && ../.venv/bin/python -m pytest -q

test-front:
	cd frontend && npm test

eval:
	.venv/bin/python eval/run_eval.py --versions v1 v2 v3

eval-demo:
	.venv/bin/python eval/run_eval.py --demo --versions v1 v2

deck:
	cd presentation && npm install --silent && node build.js

docker:
	docker compose up -d --build

lan:
	./scripts/lan.sh

publish-site:
	git add docs/site docs/card presentation/Amba_TBank.pptx presentation/Amba_TBank.pdf
	git commit -m "Ссылка на приложение: $$(grep -o 'http://[0-9.]*:[0-9]*' docs/site/index.html | head -1)" && git push

fuel-data:
	.venv/bin/python scripts/update_fuel.py
