.PHONY : venv clean install test

venv:
	virtualenv venv

clean: 
	rm -rf venv *.egg

install: venv
	. venv/bin/activate; pip install -r test-requirements.txt --use-mirrors
	. venv/bin/activate; python setup.py develop

test:
	. venv/bin/activate; nosetests
