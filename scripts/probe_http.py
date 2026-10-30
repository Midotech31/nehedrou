"""Operator HTTP timing sample. No credentials, cookies, patient routes or automatic scheduling."""
import argparse
import json
import re
import subprocess
from urllib.parse import urlsplit

FORMAT = '%{http_code} %{time_namelookup} %{time_connect} %{time_appconnect} %{time_starttransfer} %{time_total}'


def parse_sample(output):
    headers, values = output.rsplit('\n', 1)
    code, dns, connected, tls, first_byte, total = values.split()
    dns, connected, tls, first_byte, total = map(float, (dns, connected, tls, first_byte, total))
    timing = re.findall(r'^server-timing:\s*(.+)$', headers, re.IGNORECASE | re.MULTILINE)
    return {'http_status': int(code), 'dns_ms': round(dns * 1000, 3), 'tcp_after_dns_ms': round(max(connected - dns, 0) * 1000, 3),
        'tls_after_tcp_ms': round(max(tls - connected, 0) * 1000, 3), 'ttfb_ms': round(first_byte * 1000, 3),
        'total_ms': round(total * 1000, 3), 'server_timing': timing[-1].strip() if timing else None}


def sample(url):
    target = urlsplit(url)
    if target.scheme != 'https' or not target.hostname or target.username or target.password or target.path != '/healthz/' or target.query or target.fragment:
        raise ValueError('Use a credential-free HTTPS /healthz/ URL only.')
    command = ['curl', '--silent', '--show-error', '--max-time', '75', '--connect-timeout', '15',
               '--dump-header', '-', '--output', 'NUL' if __import__('os').name == 'nt' else '/dev/null',
               '--write-out', '\n' + FORMAT, url]
    result = subprocess.run(command, capture_output=True, text=True, timeout=80, check=False)
    if result.returncode:
        return {'ok': False, 'reason': 'http_probe_failed', 'curl_exit_code': result.returncode}
    report = parse_sample(result.stdout)
    report['ok'] = report['http_status'] == 200
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('--samples', type=int, default=1, choices=range(1, 6))
    parser.add_argument('--first-after-idle', action='store_true', help='Operator label only; no attempt to keep the free service awake.')
    options = parser.parse_args()
    try:
        samples = [sample(options.url) for _ in range(options.samples)]
    except (ValueError, OSError, subprocess.TimeoutExpired):
        raise SystemExit('Probe could not run. No private configuration was printed.')
    print(json.dumps({'schema': 'nehedrou-http-timings-v1', 'first_after_idle_declared': options.first_after_idle,
        'samples': samples, 'scope': 'TTFB includes network, proxy, queue, process wake-up and server work. Server-Timing app/db spans overlap and do not isolate cold-start or S3 latency.'}, indent=2))
    return 0 if all(row['ok'] for row in samples) else 1


if __name__ == '__main__':
    raise SystemExit(main())
