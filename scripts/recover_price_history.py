"""Restore only genuine dated price observations from committed snapshots."""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from monitor.value import clean_rows, day_at, prune_history

ANCHOR = '3f082c8ae18f70799f91d8c046fcc1d7e8333de5'


def merge_history(current, snapshots, day):
    result = {k: sorted(clean_rows(v, day).items()) for k, v in current.items()}
    for snapshot in snapshots:
        for key, rows in snapshot.items():
            values = clean_rows(result.get(key, []), day)
            for d, price in clean_rows(rows, day).items():
                values[d] = min(values.get(d, price), price)
            if values: result[key] = sorted(values.items())
    return prune_history(result, day)


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, encoding='utf-8')


def recover(now=None):
    now = time.time() if now is None else now
    for filename, field, day in [('state/hogar.json', 'history', int(now//86400)),
                                  ('state/state.json', 'price_history', day_at(now))]:
        path = ROOT / filename
        current = json.loads(path.read_text(encoding='utf-8'))
        # All changed snapshots in the short recovery interval, plus the last
        # pre-regression anchor. No timestamps or prices are inferred.
        commits = git('log', '--format=%H', '--since=2026-10-04T00:00:00Z', '--', filename).splitlines()
        commits = list(dict.fromkeys([ANCHOR, *commits]))
        snapshots = (json.loads(git('show', f'{commit}:{filename}')).get(field, {}) for commit in commits)
        before = current.get(field, {})
        restored = merge_history(before, snapshots, day)
        current[field] = restored
        path.write_text(json.dumps(current, ensure_ascii=False, indent=1)+'\n', encoding='utf-8')
        mature = sum(len([d for d, _ in rows if d < day]) >= 7 for rows in restored.values())
        print(f'{filename}: {len(before)} -> {len(restored)} historiales; {mature} con 7 días previos; {len(commits)} instantáneas')


if __name__ == '__main__': recover()
