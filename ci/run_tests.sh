#!/bin/bash

NOX_SESSION=test-${PYTHON_VERSION%-dev}
nox -s $NOX_SESSION --error-on-missing-interpreters
