#!/bin/sh

TESTNAME="test/$1"

if [ -z $TESTNAME ] || [ ! -f $TESTNAME ] ; then
    echo "Invalid test specified, please choose from the following:"
    for x in `(cd test/ && ls -w1 *.py | grep "test_")` ; do
        echo " - $x";
    done
    exit
else
    PYTHONPATH=$PYTHONPATH:`dirname $(readlink -f $0)` python $TESTNAME
fi

