PY ?= .venv/bin/python
.PHONY: setup data backtest test dry-run status clean
setup:            ## venv + deps
	python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r requirements.txt
data:             ## re-download the price cache (network)
	$(PY) data_loader.py --refresh
backtest:         ## full backtest from the committed cache -> results/ and README tables
	$(PY) run.py backtest
test:
	$(PY) -m pytest -q
dry-run:          ## compute today's target orders against the Alpaca paper account, submit nothing
	$(PY) run.py dry-run
status:
	$(PY) run.py status
clean:
	rm -rf .pytest_cache tsmom/__pycache__ tests/__pycache__ __pycache__
