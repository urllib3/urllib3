from __future__ import print_function

from contextlib import closing
from sys import argv, exit

from . import PoolManager
from .util.url import parse_url


if __name__ == '__main__':
    if len(argv) == 2:
        url = argv[1]
        target = parse_url(url).path.split('/')[-1]
    elif len(argv) == 3:
        url = argv[1]
        target = argv[2]
    else:
        exit('Usage: {0} <url> [target]'.format(argv[0]))

    http = PoolManager()

    with open(target, 'xb') as output:
        with closing(http.request('GET', url, preload_content=False)) as r:
            for chunk in r.stream():
                output.write(chunk)

    exit()
