#!/bin/sh

TESTNAME="$1"

if [ -z $TESTNAME ] || [ ! -f $TESTNAME ] ; then
    echo "Invalid test specified, please choose from the following:"
    for x in `(find test/ -iname '*.py' | grep "test_")` ; do
        echo " - $x";
    done
    exit
else
    PYTHONPATH=$PYTHONPATH:`dirname $(readlink -f $0)` python $TESTNAME
fi

