import urllib3
from urllib3.util import get_host

http = urllib3.PoolManager()

r1 = http.request('GET', 'http://ipv6.google.com', retries=10)
print r1.status

r2 = http.request('GET', 'http://[2a00:1450:4001:c01::67]', retries=10)
print r2.status

print r1.data
print '-'*45
print r2.data

"""
print get_host('google.com')
print get_host('http://ipv6.google.com')
print get_host('http://ipv6.google.com/test')
print get_host('http://ipv6.google.com:80')
print get_host('http://ipv6.google.com:80/test')
print get_host('[2a00:1450:4001:c01::67]')
print get_host('http://[2a00:1450:4001:c01::67]')
print get_host('http://[2a00:1450:4001:c01::67]/test')
print get_host('http://[2a00:1450:4001:c01::67]:80')
print get_host('http://[2a00:1450:4001:c01::67]:80/test')
print get_host('128.178.76.45')
print get_host('http://128.178.76.45')
print get_host('http://128.178.76.45/test')
print get_host('http://128.178.76.45:80')
print get_host('http://128.178.76.45:80/test')
"""