* [ ]  See if all tests, including integration, pass
* [ ]  Get the release pull request approved by a [CODEOWNER](https://github.com/urllib3/urllib3/blob/main/.github/CODEOWNERS)
* [ ]  Squash merge the release pull request with message "`Release <VERSION>`"
* [ ]  Tag with X.Y.Z, push tag on urllib3/urllib3 (not on your fork, update `<REMOTE>` accordingly)
  * Notice that the `<VERSION>` shouldn't have a `v` prefix (Use `1.26.6` instead of `v.1.26.6`)
  * ```
    git tag -s -a '<VERSION>' -m 'Release: <VERSION>'
    git push <REMOTE> --tags
    ```
* [ ]  Execute the `deploy` GitHub workflow.
       This requires a review from a maintainer.
* [ ]  Grab sdist and wheel from PyPI to attach to GitHub release
* [ ]  Announce on:
  
  * [ ]  GitHub releases
  * [ ]  Twitter
  * [ ]  Discord
  * [ ]  OpenCollective
  * [ ]  GitCoin Grants
* [ ]  Update Tidelift metadata
* [ ]  If this was a 1.26.x release, add changelog to the `main` branch
