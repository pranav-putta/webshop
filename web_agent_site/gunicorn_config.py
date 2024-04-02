import os

workers = 10
threads = 10

bind = "0.0.0.0:3002"

forward_allow_ips = '*'
secure_scheme_headers = {'X-Forwarded-Proto': 'https'}
