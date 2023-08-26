import urllib3

http = urllib3.PoolManager()

response = http.request('GET', 'https://www.compactcloud.co.uk')

print(response.status)
print(response.data[-128:])