#!/usr/bin/env python3
"""hf_lint.py — `hf lint .`, except that the explainer inserts' own HTML files (insert-*.html,
rendered separately with -c) are not an error: HyperFrames sees several root compositions."""
import os, re, subprocess, sys

HF = ['npx', '-y', 'hyperframes@' + os.environ.get('HF_VERSION', '0.8.181')]
r = subprocess.run(HF + ['lint', sys.argv[1] if len(sys.argv) > 1 else '.'], capture_output=True, text=True)
out = (r.stdout + r.stderr)
if r.returncode == 0:
    sys.exit(0)
errors = [l for l in out.splitlines() if l.strip().startswith('✗')]
real = [l for l in errors if 'multiple_root_compositions' not in l]
if errors and not real:
    print('hf lint: OK (insert-*.html are separate compositions, rendered on their own)')
    sys.exit(0)
print('\n'.join(out.strip().splitlines()[-40:]))
sys.exit(r.returncode or 1)
