#!/bin/bash
# Cut a new release based on the latest CHANGES.rst entry.
# Must be called from the `release` branch.

VERSION_FILE="urllib3/__init__.py"
CHANGES_FILE="CHANGES.rst"

if [ "$(git rev-parse --abbrev-ref HEAD)" != "release" ]; then
    echo "Must be called from the release branch."
    exit 1
fi

git merge master --no-commit
git checkout master -- CHANGES.rst
sed -i '' '4,9d' CHANGES.rst

version="$(grep -m1 -B1 '+++++' "$CHANGES_FILE" | head -n1 | cut -d' ' -f1)"
perl -p -i -e "s/__version__.*/__version__ = '$(version)'/" "$(VERSION_FILE)"
