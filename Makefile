.PHONY: test install docs docs-install

clean:
	rm -rf .tox
	rm -rf docs/_build

install: 
	python setup.py develop

test-install: install
	pip install -r test-requirements.txt
	pip install tox

test:
	tox

docs-install: 
	pip install sphinx

docs:
	cd docs && make html
