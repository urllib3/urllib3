#!/bin/bash

if [[ -z "$NOX_SESSION" ]]; then
  NOX_SESSION=test-${PYTHON_VERSION%-dev}
fi
nox -s $NOX_SESSION --error-on-missing-interpreters

# Make the combined coverage file to be
# uploaded as a GitHub Actions artifact.
if [ -f .coverage ] && [ ! -z "$GITHUB_RUN_ID" ]; then
  # The 'tr -d \0' is to remove the nul byte prefix added by shuf -z
  RANDOM_ID=$(shuf -zer -n10  {A..Z} {a..z} {0..9} | tr -d '\0')
  cp .coverage ".coverage.$GITHUB_RUN_ID-$RANDOM_ID"
fi
