.PHONY : venv clean install test

venv:
	virtualenv venv

clean: 
	rm -rf venv *.egg

install: venv
	. venv/bin/activate; python setup.py install

test:
	python setup.py test
