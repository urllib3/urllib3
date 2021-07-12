* [ ]  See if all tests, including integration, pass
* [ ]  Get the release pull request approved by a [CODEOWNER](https://github.com/urllib3/urllib3/blob/main/.github/CODEOWNERS)
* [ ]  Squash merge the release pull request with message "`Release <VERSION>`"
* [ ]  Tag with X.Y.Z, push tag on urllib3/urllib3 (not on your fork, update `<REMOTE>` accordingly)
  
  * Notice that the `<VERSION>` shouldn't have a `v` prefix (Use `1.26.6` instead of `v.1.26.6`)
  * ```
    git tag -a '<VERSION>' -m 'Release: <VERSION>'
    git push <REMOTE> --tags
    ```
* [ ]  Push to PyPI
  
  * ```
    cd /tmp
    git clone ssh://git@github.com/urllib3/urllib3
    cd urllib3
    git checkout <TAG/VERSION>
    python -m venv
    source venv/bin/activate
    python -m pip install -U pip
    python -m pip install -U twine setuptools wheel
    python setup.py sdist bdist_wheel
    
    twine check dist/*
    # Inspect the output to make sure it looks right
    # Check versions, should be 1 wheel 1 sdist
    
    twine upload dist/*
    ```
* [ ]  Grab sdist and wheel from PyPI to attach to GitHub release
* [ ]  Announce on:
  
  * [ ]  GitHub releases
  * [ ]  Twitter
  * [ ]  Discord
  * [ ]  OpenCollective
  * [ ]  GitCoin Grants
* [ ]  Update Tidelift metadata
