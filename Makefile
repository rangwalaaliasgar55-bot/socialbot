.PHONY: install dev test run dashboard clean

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

test:
	pytest

run:
	socialbot run

dashboard:
	socialbot dashboard

clean:
	rm -rf build dist *.egg-info .pytest_cache __pycache__ socialbot.db
