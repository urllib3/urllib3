====================================
API stability and deprecation policy
====================================

* urllib3 will not wait until a "major" version release (e.g., 3.0.0, 4.0.0,
  etc.) to make a backwards incompatible change, but we will endeavor
  to pick a release that we anticipate to be far enough in the future

* A release that is "far enough in the future" may be 4 or more "minor"
  version releases (e.g., announced when releasing 3.0.1 and "broken" in 3.4.0)

* urllib3 also reserves the right to push that further out if the release ends
  up coming up more quickly than anticipated by the maintainers (e.g., if in
  3.0.1 we announced a breaking change in 3.4.0, and felt we had not given
  sufficient time prior to releasing 3.3.0, we may change the warning to
  communicate the breaking change may happen in 3.5.0 or 3.7.0)

* All anticipated breaking changes will be:

  * Documented here at https://urllib3.readthedocs.io/
  * Included in release notes at the time of decision
  * Re-announced the minor release prior to planned breaking changes
  * Communicated via sponsorship channels
