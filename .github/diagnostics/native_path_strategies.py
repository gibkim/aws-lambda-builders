"""Real-filesystem path-strategy diagnostic. Does not import or edit product code.

Run on the desired OS: python native_path_strategies.py --output strategy-results.json
Wrong-target results are data, not process failures. The JSON records native source
lookup first, so junction semantics are measured rather than assumed.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from tempfile import TemporaryDirectory


STRATEGIES = (
    'joined_absolute',
    'parent_realpath_absolute',
    'rebased_relative',
    'rebased_destination_realpath',
    'rebased_both_parents_realpath',
    'extended_absolute',
)
SCENARIOS = (
    'ordinary_parent',
    'source_parent_symlink',
    'source_parent_junction',
    'source_parent_alias_dotdot',
    'internal_target_symlink_dotdot',
    'internal_target_junction_dotdot',
    'destination_parent_symlink',
    'destination_parent_junction',
    'chain',
    'broken',
    'loop',
)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def junction(link, target):
    if os.name != 'nt':
        raise NotImplementedError('junction is Windows only')
    subprocess.run(
        ['cmd.exe', '/d', '/c', 'mklink', '/J', str(link), str(target)],
        check=True, capture_output=True, text=True,
    )


def state(path):
    result = {'is_symlink': path.is_symlink(), 'lexists': os.path.lexists(path)}
    try:
        result['text'] = path.read_text(encoding='utf-8')
    except OSError as error:
        result['error_type'] = type(error).__name__
        result['errno'] = error.errno
        result['winerror'] = getattr(error, 'winerror', None)
    return result


def comparable(info):
    if 'text' in info:
        return ('text', info['text'])
    return ('error', info.get('errno'), info.get('winerror'))


def build(root, scenario):
    physical = root / 'real' / 'artifacts'
    physical.mkdir(parents=True)
    write(root / 'real' / 'target', 'physical original')
    write(root / 'target', 'logical or lexical decoy')
    dependency = physical / 'dependency'
    raw = os.path.join('..', 'target')
    source = dependency
    destination_parent = root / 'destination'
    destination_parent.mkdir()
    mutation = None

    if scenario == 'source_parent_symlink':
        alias = root / 'source_alias'
        alias.symlink_to(physical, target_is_directory=True)
        source = alias / 'dependency'
    elif scenario == 'source_parent_junction':
        alias = root / 'source_junction'
        junction(alias, physical)
        source = alias / 'dependency'
    elif scenario == 'source_parent_alias_dotdot':
        nested = root / 'real' / 'nested'
        nested.mkdir()
        alias = root / 'source_alias'
        alias.symlink_to(nested, target_is_directory=True)
        lexical = root / 'artifacts'
        lexical.mkdir()
        (lexical / 'dependency').symlink_to(raw)
        source = alias / '..' / 'artifacts' / 'dependency'
    elif scenario in ('internal_target_symlink_dotdot', 'internal_target_junction_dotdot'):
        deep = root / 'other' / 'deep'
        deep.mkdir(parents=True)
        write(root / 'other' / 'target', 'internal alias original')
        write(physical / 'target', 'internal lexical decoy')
        if scenario == 'internal_target_symlink_dotdot':
            (physical / 'subalias').symlink_to(deep, target_is_directory=True)
        else:
            junction(physical / 'subalias', deep)
        raw = os.path.join('subalias', '..', 'target')
    elif scenario in ('destination_parent_symlink', 'destination_parent_junction'):
        actual_destination = root / 'deep' / 'physical_destination'
        actual_destination.mkdir(parents=True)
        destination_parent = root / 'destination_alias'
        if scenario == 'destination_parent_symlink':
            destination_parent.symlink_to(actual_destination, target_is_directory=True)
        else:
            junction(destination_parent, actual_destination)
    elif scenario == 'chain':
        write(root / 'first', 'chain first')
        write(root / 'second', 'chain second')
        middle = physical / 'middle'
        middle.symlink_to(os.path.join('..', '..', 'first'))
        raw = 'middle'
        mutation = middle
    elif scenario == 'broken':
        raw = os.path.join('..', 'missing')
    elif scenario == 'loop':
        raw = 'dependency'

    dependency.symlink_to(raw)
    return source, destination_parent / 'dependency', mutation


def target_for(strategy, source, destination):
    parent = os.path.dirname(source)
    destination_parent = os.path.dirname(destination)
    raw = os.readlink(source)
    joined = os.path.join(parent, raw)
    if strategy == 'joined_absolute':
        return str(Path(joined).absolute())
    if strategy == 'parent_realpath_absolute':
        return str(Path(os.path.join(os.path.realpath(parent), raw)).absolute())
    if strategy == 'rebased_relative':
        return os.path.join(os.path.relpath(parent, destination_parent), raw)
    if strategy == 'rebased_destination_realpath':
        return os.path.join(os.path.relpath(parent, os.path.realpath(destination_parent)), raw)
    if strategy == 'rebased_both_parents_realpath':
        return os.path.join(os.path.relpath(os.path.realpath(parent), os.path.realpath(destination_parent)), raw)
    if strategy == 'extended_absolute':
        if os.name != 'nt':
            raise NotImplementedError('extended absolute prefix is Windows only')
        target = str(Path(joined).absolute())
        if target.startswith('\\\\?\\'):
            return target
        if target.startswith('\\\\'):
            return '\\\\?\\UNC\\' + target[2:]
        return '\\\\?\\' + target
    raise AssertionError(strategy)


def probe(scenario, strategy):
    result = {'scenario': scenario, 'strategy': strategy}
    try:
        with TemporaryDirectory(prefix='builders-native-strategy-') as directory:
            source, destination, middle = build(Path(directory), scenario)
            result.update({
                'source': str(source),
                'source_parent_realpath': os.path.realpath(source.parent),
                'destination': str(destination),
                'destination_parent_realpath': os.path.realpath(destination.parent),
                'raw_readlink': os.readlink(source),
                'original': state(source),
            })
            target = target_for(strategy, str(source), str(destination))
            result['symlink_target_argument'] = target
            os.symlink(target, destination)
            result['created_readlink'] = os.readlink(destination)
            result['copied'] = state(destination)
            result['same_native_meaning'] = comparable(result['original']) == comparable(result['copied'])
            if 'text' in result['original'] and 'text' in result['copied']:
                result['samefile'] = os.path.samefile(source, destination)
            if middle is not None:
                middle.unlink()
                middle.symlink_to(os.path.join('..', '..', 'second'))
                result['after_chain_retarget_original'] = state(source)
                result['after_chain_retarget_copied'] = state(destination)
                result['chain_retarget_preserved'] = (
                    comparable(result['after_chain_retarget_original'])
                    == comparable(result['after_chain_retarget_copied'])
                )
            if 'text' in result['original']:
                before_removal = state(destination)
                source.unlink()
                result['after_original_link_removed'] = state(destination)
                result['independent_of_original_link'] = (
                    comparable(before_removal) == comparable(result['after_original_link_removed'])
                )
    except NotImplementedError as error:
        result['skipped'] = str(error)
    except Exception as error:
        result['probe_error'] = {'type': type(error).__name__, 'message': str(error),
                                 'errno': getattr(error, 'errno', None),
                                 'winerror': getattr(error, 'winerror', None)}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='strategy-results.json')
    args = parser.parse_args()
    results = [probe(scenario, strategy) for scenario in SCENARIOS for strategy in STRATEGIES]
    payload = {'platform': platform.platform(), 'python': sys.version, 'executable': sys.executable,
               'notes': ['No product imports or edits.',
                         'Native original-link lookup is the expected value.',
                         'Only file targets are used; path resolution, not directory flag policy, is compared.',
                         'Cross-volume relpath ValueError is an explicit untested limitation.',
                         'No product copy fallback is emulated; native path strategy only.'],
               'results': results}
    Path(args.output).write_text(json.dumps(payload, indent=2), encoding='utf-8')
    for strategy in STRATEGIES:
        rows = [row for row in results if row['strategy'] == strategy]
        print(strategy, 'match', sum(row.get('same_native_meaning') is True for row in rows),
              'mismatch', sum(row.get('same_native_meaning') is False for row in rows),
              'errors', sum('probe_error' in row for row in rows),
              'skipped', sum('skipped' in row for row in rows))
    print('results:', Path(args.output).absolute())


if __name__ == '__main__':
    main()
