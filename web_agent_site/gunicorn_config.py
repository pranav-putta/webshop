import os

workers = 25
threads = 1

bind = "0.0.0.0:3000"

forward_allow_ips = '*'
secure_scheme_headers = {'X-Forwarded-Proto': 'https'}
