"""Probe only. Copy alongside native_path_strategies.py; no product imports."""
import errno
import json
import os
from pathlib import Path
import platform
import sys
from tempfile import TemporaryDirectory
import native_path_strategies as fixtures


def origin_target(source, active=()):
    key = os.path.normcase(os.path.abspath(source))
    if key in active or len(active) >= 40:
        raise OSError(errno.ELOOP, 'source-parent symlink cycle', source)
    raw = os.readlink(source)
    if os.path.isabs(raw):
        return raw
    if os.name != 'nt':
        return os.path.join(os.path.dirname(source), raw)
    parent = os.path.dirname(os.path.abspath(source))
    target = os.path.normpath(raw)
    while target == os.pardir or target.startswith(os.pardir + os.sep):
        seen = set()
        while os.path.islink(parent):
            parent_key = os.path.normcase(os.path.abspath(parent))
            if parent_key in seen or len(seen) >= 40:
                raise OSError(errno.ELOOP, "source-parent symlink cycle", parent)
            seen.add(parent_key)
            parent = origin_target(parent, active + (key,))
        parent = os.path.dirname(parent)
        target = target[len(os.pardir):].lstrip(os.sep) or os.curdir
    return os.path.join(parent, target)


EXTRA = ('deep_alias_one_up', 'deep_alias_two_up', 'deep_junction_two_up',
         'relative_alias_chain', 'symlink_via_junction', 'past_drive_root')


def extra(root, scenario):
    source, destination, _ = fixtures.build(root, 'ordinary_parent')
    physical = source.parent
    source.unlink()
    (physical / 'sub').mkdir()
    raw = os.path.join('..', '..', 'target')
    actual = physical / 'sub' / 'dependency'
    alias = root / 'alias'
    if scenario == 'past_drive_root':
        if os.name != 'nt':
            raise NotImplementedError('Windows drive-root traversal only')
        raw = os.path.join(*(['..'] * 64), os.path.splitdrive(str(root / 'target'))[1].lstrip('\\/'))
        actual, source = physical / 'dependency', physical / 'dependency'
    elif scenario == 'relative_alias_chain':
        (root / 'second_alias').symlink_to(physical, target_is_directory=True)
        alias.symlink_to('second_alias', target_is_directory=True)
        actual, source = physical / 'dependency', alias / 'dependency'
        raw = os.path.join('..', 'target')
    elif scenario == 'symlink_via_junction':
        bridge = root / 'bridge'
        fixtures.junction(bridge, physical)
        alias.symlink_to(bridge / 'sub', target_is_directory=True)
        source = alias / 'dependency'
    else:
        if scenario == 'deep_junction_two_up':
            fixtures.junction(alias, physical)
        else:
            alias.symlink_to(physical, target_is_directory=True)
        source = alias / 'sub' / 'dependency'
        if scenario == 'deep_alias_one_up':
            raw = os.path.join('..', 'target')
            fixtures.write(physical / 'target', 'deep parent original')
    actual.symlink_to(raw)
    return source, destination, None


def probe(scenario):
    row = {'scenario': scenario}
    try:
        with TemporaryDirectory(prefix='builders-origin-v3-') as directory:
            root = Path(directory)
            source, destination, middle = extra(root, scenario) if scenario in EXTRA else fixtures.build(root, scenario)
            row.update(source=str(source), destination=str(destination), raw_readlink=os.readlink(source),
                       original=fixtures.state(source))
            target = origin_target(str(source))
            row['target_argument'] = target
            os.symlink(target, destination)
            row['created_readlink'], row['copied'] = os.readlink(destination), fixtures.state(destination)
            row['same_native_meaning'] = fixtures.comparable(row['original']) == fixtures.comparable(row['copied'])
            if 'text' in row['original'] and 'text' in row['copied']:
                row['samefile'] = os.path.samefile(source, destination)
            if middle is not None:
                middle.unlink()
                middle.symlink_to(os.path.join('..', '..', 'second'))
                row['chain_retarget_preserved'] = fixtures.comparable(fixtures.state(source)) == fixtures.comparable(fixtures.state(destination))
            if 'text' in row['original']:
                before = fixtures.state(destination)
                source.unlink()
                row['original_link_removal_preserved'] = fixtures.comparable(before) == fixtures.comparable(fixtures.state(destination))
    except NotImplementedError as error:
        row['skipped'] = str(error)
    except Exception as error:
        row['probe_error'] = {'type': type(error).__name__, 'message': str(error), 'errno': getattr(error, 'errno', None)}
    return row


if __name__ == '__main__':
    rows = [probe(scenario) for scenario in fixtures.SCENARIOS + EXTRA]
    output = Path(sys.argv[1] if len(sys.argv) > 1 else 'v3-origin-aware-results.json')
    output.write_text(json.dumps({'platform': platform.platform(), 'python': sys.version,
                                 'notes': ['Origin-aware proposed algorithm, not product code.',
                                           'Drive-root saturation is deliberately unmodified for comparison.'],
                                 'results': rows}, indent=2), encoding='utf-8')
    print(json.dumps(rows, indent=2))
