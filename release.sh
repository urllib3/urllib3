#!/bin/bash
# Cut a new release based on the latest CHANGES.rst entry.
# Must be called from the `release` branch.

VERSION_FILE="src/urllib3/__init__.py"
CHANGES_FILE="CHANGES.rst"

if [ "$(git rev-parse --abbrev-ref HEAD)" != "release" ]; then
    echo "Must be called from the release branch."
    exit 1
fi

# Merge master
git merge master --no-commit
git checkout master -- CHANGES.rst

# Remove dev section and update version.
sed -i '' '4,9d' CHANGES.rst
version="$(grep -m1 -B1 -- '-----' "${CHANGES_FILE}" | head -n1 | cut -d' ' -f1)"
perl -p -i -e "s/__version__.*/__version__ = '${version}'/" "${VERSION_FILE}"
git diff

# Confirm
read -n1 -p "Good? [Y/n] " r
if ! [[ $r =~ ^([yY]*)$ ]]; then
    echo "Stopped."
    exit 2
fi

# Prepare commit
git commit -a -m "Merging new release version: ${version}"
git tag ${version} -s -m "Release: ${version}"

# Build package
make clean
python setup.py sdist bdist_wheel

# TODO: Shove a unicorn in here, or something.

echo "Release is ready. Publish it when ready:"
echo "git push origin"
echo "twine upload dist/*"
