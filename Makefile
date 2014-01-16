.PHONY: test install docs docs-install

venv:
	virtualenv venv

clean:
	rm -rf venv
	rm -rf .tox

install: venv
	. venv/bin/activate; python setup.py develop

test-install: venv install
	. venv/bin/activate; pip install -r test-requirements.txt
	. venv/bin/activate; pip install tox

test:
	. venv/bin/activate; tox

docs-install: venv
	. venv/bin/activate; pip install sphinx

docs:
	. venv/bin/activate; cd docs && make html
