import errno
import json
from pathlib import Path
import platform
import subprocess
import sys

from aws_lambda_builders import utils
import v3_origin_aware_probe as experiment

root = Path.cwd().resolve()
assert Path(utils.__file__).resolve().is_relative_to(root)
experiment.origin_target = utils._get_symlink_target
rows = [experiment.probe(name) for name in experiment.fixtures.SCENARIOS + experiment.EXTRA]
failures = []
for row in rows:
    if row['scenario'] == 'past_drive_root':
        ok = row.get('original', {}).get('errno') == errno.EINVAL and row.get('probe_error', {}).get('errno') == errno.EINVAL
    else:
        ok = row.get('same_native_meaning') is True and row.get('chain_retarget_preserved', True) and row.get('original_link_removal_preserved', True)
    if not ok:
        failures.append(row)
report = {'platform': platform.platform(), 'python': platform.python_version(),
          'source_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
          'source_tree': subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], text=True).strip(),
          'module_path': str(Path(utils.__file__).resolve()), 'results': rows, 'failures': failures}
Path('windows-product-adversarial.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps({'source_head': report['source_head'], 'passed': len(rows) - len(failures), 'failed': len(failures)}))
for row in failures:
    print(json.dumps(row, indent=2))
assert not failures
