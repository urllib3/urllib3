REQUIREMENTS_FILE=dev-requirements.txt
REQUIREMENTS_OUT=dev-requirements.txt.log
SETUP_OUT=*.egg-info


all: setup requirements

virtualenv:
ifndef VIRTUAL_ENV
	$(error Must be run inside of a virtualenv)
endif

setup: virtualenv $(SETUP_OUT)

$(SETUP_OUT): setup.py setup.cfg
	python setup.py develop
	touch $(SETUP_OUT)

requirements: setup $(REQUIREMENTS_OUT)

piprot: setup
	pip install piprot
	piprot -x $(REQUIREMENTS_FILE)

$(REQUIREMENTS_OUT): $(REQUIREMENTS_FILE)
	pip install -r $(REQUIREMENTS_FILE) | tee -a $(REQUIREMENTS_OUT)
	python setup.py develop

clean:
	find . -name "*.py[oc]" -delete
	find . -name "__pycache__" -delete
	rm -f $(REQUIREMENTS_OUT)
	rm -rf docs/_build build/ dist/

test: requirements
	nosetests

test-all: requirements
	tox

test-gae: requirements
	tox -e gae

docs:
	cd docs && pip install -r doc-requirements.txt && make html

release:
	./release.sh


.PHONY: docs
