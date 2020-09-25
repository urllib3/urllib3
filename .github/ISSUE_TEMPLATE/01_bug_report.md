---
name: 🐞 Bug report
about: Something is broken
---

### Subject

Describe the issue here.

### Environment

Describe your environment.
At least, paste here the output of:

```python
from __future__ import print_function
import platform
import urllib3
print("OS     : %s" % (platform.platform(), ))
print("Python : %s" % (platform.python_build()[0], ))
print("urllib3: %s" % (urllib3.__version__, ))
```

### Steps to Reproduce

A simple and isolated way to reproduce the issue. A code snippet would be great.

### Expected Behavior

What should happen.

### Actual Behavior

What happens instead.
You may attach logs, packet captures, etc.
