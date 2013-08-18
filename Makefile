.PHONY : venv clean install test

venv:
	virtualenv venv

clean: 
	rm -rf venv *.egg

install: venv
	. venv/bin/activate; python setup.py develop
	. venv/bin/activate; pip install -r test-requirements.txt --use-mirrors

test:
	nosetests
