REQUIREMENTS_FILE=dev-requirements.txt
REQUIREMENTS_OUT=dev-requirements.txt.log
SETUP_OUT=*.egg-info

.PHONY: all
all: setup requirements

.PHONY: virtualenv
virtualenv:
ifndef VIRTUAL_ENV
	$(error Must be run inside of a virtualenv)
endif

.PHONY: setup
setup: virtualenv $(SETUP_OUT)

.PHONY: $(SETUP_OUT)
$(SETUP_OUT): setup.py setup.cfg
	python setup.py develop
	touch $(SETUP_OUT)

.PHONY: requirements
requirements: setup $(REQUIREMENTS_OUT)

.PHONY: piprot
piprot: setup
	pip install piprot
	piprot -x $(REQUIREMENTS_FILE)

.PHONY: $(REQUIREMENTS_OUT)
$(REQUIREMENTS_OUT): $(REQUIREMENTS_FILE)
	pip install -r $(REQUIREMENTS_FILE) | tee -a $(REQUIREMENTS_OUT)
	python setup.py develop

.PHONY: clean
clean:
	find . -name "*.py[oc]" -delete
	find . -name "__pycache__" -delete
	rm -f $(REQUIREMENTS_OUT)
	rm -rf docs/_build build/ dist/

.PHONY: test
test: requirements
	nosetests

.PHONY: test-all
test-all: requirements
	tox

.PHONY: test-gae
test-gae: requirements
ifndef GAE_PYTHONPATH
	$(error GAE_PYTHONPATH must be set)
endif
	tox -e gae

.PHONY: docs
docs:
	tox -e docs

.PHONY: release
release:
	./release.sh


