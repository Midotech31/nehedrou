"""One fixed non-clinical object for an explicit operator read sample.

Provisioning is an operator task. Importing this module or opening the diagnostics
page never writes an object or accepts a client-selected storage key.
"""
import hashlib

PROBE_KEY = 'operator-probe/nehedrou-read-v1.txt'
PROBE_BODY = b'Nehedrou technical storage probe v1. No personal or clinical data.\n'
PROBE_SHA256 = hashlib.sha256(PROBE_BODY).hexdigest()
