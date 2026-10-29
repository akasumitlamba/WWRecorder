"""Check the exact Windows lock against OSV; preserve an auditable result."""
import argparse
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.request


def check_package(name, version, opener=urllib.request.urlopen):
    request = urllib.request.Request('https://api.osv.dev/v1/query',
        data=json.dumps({'package': {'ecosystem': 'PyPI', 'name': name}, 'version': version}).encode(),
        headers={'Content-Type': 'application/json', 'User-Agent': 'WWRecorder dependency audit'})
    for attempt in range(3):
        try:
            with opener(request, timeout=20) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise ValueError('Dependency advisory response exceeds limit')
            data = json.loads(raw)
            return {'name': name, 'version': version,
                    'advisories': sorted({v['id'] for v in data.get('vulns', [])})}
        except Exception as exc:
            if attempt == 2:
                return {'name': name, 'version': version, 'error': str(exc)}
            time.sleep(attempt + 1)


def audit(lock, output):
    raw = Path(lock).read_bytes()
    packages = re.findall(r'^([\w.-]+)==([^\s]+) --hash=', raw.decode(), re.MULTILINE)
    if not packages:
        raise ValueError('Dependency lock is empty')
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda item: check_package(*item), packages))
    report = {'checked_at_utc': datetime.now(timezone.utc).isoformat(),
              'lock_sha256': hashlib.sha256(raw).hexdigest(), 'packages': results,
              'scope': 'OSV exact PyPI versions; separate native library review remains required'}
    report['passed'] = not any(r.get('advisories') or r.get('error') for r in results)
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--lock', default='requirements-windows.lock')
    parser.add_argument('--output', default='work/build/security-evidence/dependency-audit.json')
    args = parser.parse_args()
    result = audit(args.lock, args.output)
    print(json.dumps({'passed': result['passed'], 'packages': len(result['packages']), 'report': args.output}))
    raise SystemExit(0 if result['passed'] else 1)
