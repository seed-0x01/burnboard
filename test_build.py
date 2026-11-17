#!/usr/local/bin/python3
"""Falsification test: burnboard's streak + death figures come from the audit file.

Every fixture writes a SYNTHETIC audit to a temp path, rebuilds the page with
BURNBOARD_AUDIT pointed at it, and asserts the rendered numbers + embedded
metrics follow the data. If any number were baked into the HTML, a fixture
would fail. Run: python3 test_build.py
"""
import json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, 'build.py')


def row(ts, tokens, err=None, model='hy4-flash-free'):
    return {
        'ts': ts, 'job_name': 'cron', 'model': model,
        'total_tokens': tokens, 'prompt_tokens': tokens, 'completion_tokens': 0,
        'error': err, 'duration_ms': 1000, 'response_silent': False,
    }


def build(rows, tmp):
    audit = os.path.join(tmp, 'audit.jsonl')
    with open(audit, 'w') as f:
        for r in rows:
            f.write(json.dumps(r) + '\n')
    out = os.path.join(tmp, 'out.html')
    env = dict(os.environ, BURNBOARD_AUDIT=audit)
    subprocess.check_call([sys.executable, BUILD, out], env=env,
                          stdout=subprocess.DEVNULL)
    text = open(out).read()
    mm = re.search(r'<script type="application/json" id="data">(.*?)</script>',
                   text, re.S)
    assert mm, 'embedded data blob missing'
    data = json.loads(mm.group(1))
    assert 'id="streak">__STREAK__' not in text, 'streak placeholder unreplaced'
    return data, text


def run():
    with tempfile.TemporaryDirectory() as d:
        # A — a cap death, then three clean runs: cap streak must be 3.
        A = [
            row('2026-11-17T01:00:00Z', 100,
                'Daily limit exceeded: $3.01 > $3.00 max', model='blockrun/auto'),
            row('2026-11-17T02:00:00Z', 200),
            row('2026-11-17T03:00:00Z', 300),
            row('2026-11-17T04:00:00Z', 400),
        ]
        da, ha = build(A, d)
        m = da['metrics']
        assert m['cap_deaths'] == 1, m
        assert m['streak_cap'] == 3, m
        assert m['streak_all'] == 3, m
        assert m['longest_clean'] == 3, m
        assert '<b>3</b> consecutive runs' in ha, 'rendered cap streak wrong'
        assert 'Daily limit exceeded: $3.01 &gt; $3.00 max' in ha or \
               'Daily limit exceeded' in ha, 'death list not rendered'

        # B — death is the LAST row: streak must collapse to 0, and A's
        # "3 consecutive runs" must NOT appear (proves it is not baked in).
        B = [
            row('2026-11-17T05:00:00Z', 100),
            row('2026-11-17T06:00:00Z', 200, 'content_policy_blocked'),
        ]
        db, hb = build(B, d)
        assert db['metrics']['streak_all'] == 0, db['metrics']
        assert db['metrics']['cap_deaths'] == 0, db['metrics']
        assert '<b>3</b> consecutive runs' not in hb, 'baked-in number detected'

        # C — empty audit: zeros, honest "no cap death by definition".
        dc, hc = build([], d)
        assert dc['metrics']['runs'] == 0, dc['metrics']
        assert dc['metrics']['streak_cap'] == 0, dc['metrics']
        assert 'No <b>Daily limit exceeded</b> death' in hc

        # D — all clean, no deaths anywhere: full-length streak.
        D = [row('2026-11-17T07:00:00Z', 10), row('2026-11-17T08:00:00Z', 20)]
        dd, hd = build(D, d)
        assert dd['metrics']['cap_deaths'] == 0, dd['metrics']
        assert dd['metrics']['streak_all'] == 2, dd['metrics']
        assert '<b>2</b> runs by definition' in hd

        # E — numeric binding: doubling tokens across rows must double the
        # embedded total, and the build-time-rendered note must follow the data.
        E = [row('2026-11-17T09:00:00Z', 1000), row('2026-11-17T10:00:00Z', 2000)]
        de, he = build(E, d)
        total_e = sum(r['tokens'] for r in de['rows'])
        assert total_e == 3000, total_e
        assert '<p class="note">2/2 runs completed (100%)' in he, \
            'build-time note not bound to data'

    print('PASS: 5 fixtures — cap streak, death-last collapse, empty, '
          'all-clean, numeric binding. All figures data-bound.')


if __name__ == '__main__':
    run()
