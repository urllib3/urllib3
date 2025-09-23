# Security Policy

## Reporting a Vulnerability

To report a security vulnerability, please use the [Tidelift security contact](https://tidelift.com/security).
Tidelift will coordinate the fix and disclosure with maintainers.

Please do not file a public GitHub issue for security reports.

When reporting, if possible, include:
- A clear description of the issue and potential impact
- Steps to reproduce or a proof of concept
- Affected urllib3 version(s) and environment details
- Any suggested mitigations

We typically acknowledge reports within a few business days.


## Supported Versions

Only the main branch (the 2.x release line) receives updates, including
security fixes. Older release lines (e.g., 1.x) are not maintained. If you are
using an older version, please upgrade to the latest 2.x release to receive
fixes.

When reporting a potential vulnerability, confirm that it reproduces against
the latest 2.x version.


## Our Process

We follow the [Tidelift security process](https://support.tidelift.com/hc/en-us/articles/4406287910036-Security-process)
for coordinated vulnerability disclosure. In brief:
- Intake and triage: Reports are received privately via Tidelift, validated,
  and scoped (affected versions, severity).
- Private coordination: Tidelift facilitates communication between the reporter
  and the urllib3 maintainers.
- Fix and review: We develop, review, and prepare patches (including backports
  to supported versions when appropriate) and mitigation guidance.
- Timeline and embargo: We agree on a reasonable disclosure timeline based on
  impact and fix complexity; timelines may be accelerated for active
  exploitation or extended for complex fixes.
- CVE and advisory: We request and manage CVE IDs via GitHub Security
  Advisories and prepare public guidance. If desired, we credit the reporter
  and involved maintainers in the advisory.
- Coordinated release: We publish patched releases and the advisory at the
  agreed time.


## Advisories and CVEs

We publish our security advisories on GitHub at [the following page](https://github.com/urllib3/urllib3/security/advisories).
We request and manage CVE IDs using GitHub Security Advisories, and published
advisories include CVE identifiers (when assigned) and severity information.

To receive notifications when new advisories are published, open the repository
page, choose *Watch* → *Custom*, and enable *Security alerts*. You can also
enable *Releases* to be notified when patched versions are published.
