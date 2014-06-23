REQUIREMENTS_FILE=dev-requirements.txt
REQUIREMENTS_OUT=dev-requirements.txt.log
SETUP_OUT=*.egg-info


all: setup requirements

requirements: $(REQUIREMENTS_OUT)

piprot: requirements
	piprot -x $(REQUIREMENTS_FILE)

$(REQUIREMENTS_OUT): $(REQUIREMENTS_FILE)
	pip install -r $(REQUIREMENTS_FILE) | tee -a $(REQUIREMENTS_OUT)
	python setup.py develop

setup: virtualenv $(SETUP_OUT)

$(SETUP_OUT): setup.py setup.cfg
	python setup.py develop
	touch $(SETUP_OUT)

virtualenv:
ifndef VIRTUAL_ENV
	$(error Must be run inside of a virtualenv)
endif

clean:
	find . -name "*.py[oc]" -delete
	find . -name "__pycache__" -delete
	rm $(REQUIREMENTS_OUT)

test: setup requirements
	nosetests

test-all: setup requirements
	tox

docs: setup requirements
	cd docs && make html

release: test-all clean
	./release.sh
