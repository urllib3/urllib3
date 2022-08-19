version: 2

build:
  os: ubuntu-22.04
  tools:
    python: "3"

python:
  install:
    - requirements: docs/requirements.txt
    - method: pip
      path: .
      extra_requirements:
        - brotli
        - secure
        - socks
        - zstd

sphinx:
  fail_on_warning: true
