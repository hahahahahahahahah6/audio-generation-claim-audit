"""Static documentation and source inspection; inspected code is never executed."""
import argparse
import ast
import fnmatch
import json
import os
from pathlib import Path
import re

from . import __version__
from .phrases import AUDIOGENERATION, NOAUDIOGENERATION

PIPELINES = {'AudioLDMPipeline', 'AudioLDM2Pipeline', 'StableAudioPipeline'}
MODELS = {'MusicgenForConditionalGeneration', 'MusicgenModel'}


def normalize(text):
    return ' '.join(text.lower().replace("n't", ' not').replace('-', ' ').split())


def prose(text):
    lines = []
    fence = None
    for line in text.splitlines():
        match = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                fence = None
            continue
        if match:
            fence = match[1]
            lines.append('')
        else:
            lines.append(line)
    return [normalize(p) for p in re.split(r'\n\s*\n', '\n'.join(lines)) if p.strip()]


def remove_matches(text, phrases):
    found = False
    for phrase in sorted(phrases, key=lambda p: (-len(p), p)):
        text, count = re.subn(r'\b' + re.escape(phrase) + r'\b', ' ', text)
        found = found or bool(count)
    return text, found


def claims(text):
    positive = negative = False
    for paragraph in prose(text):
        remaining, neg = remove_matches(paragraph, NOAUDIOGENERATION)
        _, pos = remove_matches(remaining, AUDIOGENERATION)
        positive |= pos
        negative |= neg
    return positive, negative


def evidence(source):
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return False
    aliases = {}
    shadowed = set()
    # Bindings are deliberately module-local; no cross-file inference.
    for node in tree.body:
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split('.')[0]] = item.name if item.asname else item.name.split('.')[0]
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                aliases[item.asname or item.name] = node.module + '.' + item.name
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            shadowed.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                shadowed.update(n.id for n in ast.walk(target) if isinstance(n, ast.Name))

    def resolve(node):
        if isinstance(node, ast.Name):
            return None if node.id in shadowed else aliases.get(node.id)
        if isinstance(node, ast.Attribute):
            base = resolve(node.value)
            return base + '.' + node.attr if base else None
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        resolved = resolve(func)
        leaf = resolved.rsplit('.', 1)[-1] if resolved else None
        if leaf in PIPELINES | MODELS:
            return True
        if isinstance(func, ast.Attribute):
            base = resolve(func.value)
            base_leaf = base.rsplit('.', 1)[-1] if base else None
            if func.attr in {'from_pretrained', 'from_single_file'} and base_leaf in PIPELINES:
                return True
            if func.attr == 'get_pretrained' and base_leaf == 'MusicGen':
                return True
            if func.attr == 'generate' and isinstance(func.value, ast.Attribute) and func.value.attr == 'music':
                return True
        if leaf == 'pipeline':
            tasks = list(node.args[:1]) + [kw.value for kw in node.keywords if kw.arg == 'task']
            for task in tasks:
                if isinstance(task, ast.Constant) and isinstance(task.value, str):
                    value = normalize(task.value)
                    if 'text to audio' in value or 'audio generation' in value:
                        return True
    return False


def audit(root, ignore=()):
    root = Path(root)
    if not root.is_dir() or not os.access(root, os.R_OK | os.X_OK):
        raise ValueError('Root must be a readable directory')
    positive = negative = production = test = False
    count = 0
    def walk_error(error):
        raise error
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        dirs[:] = sorted(d for d in dirs if not (Path(directory) / d).is_symlink())
        for name in sorted(files):
            path = Path(directory) / name
            rel = path.relative_to(root)
            if path.is_symlink() or any(fnmatch.fnmatch(rel.as_posix(), pattern) for pattern in ignore):
                continue
            doc = rel.as_posix() == 'README.md' or (path.suffix == '.md' and 'docs' in rel.parts[:-1])
            source = path.suffix == '.py' and not {'fixtures', 'docs', 'examples'}.intersection(rel.parts[:-1])
            if not (doc or source):
                continue
            text = path.read_text(encoding='utf-8')
            count += 1
            if doc:
                pos, neg = claims(text)
                positive |= pos
                negative |= neg
            if source and evidence(text):
                is_test = 'tests' in rel.parts[:-1] or name.startswith('test_') or name.endswith('_test.py')
                test |= is_test
                production |= not is_test
    findings = []
    if positive and not production:
        findings.append(dict(rule='documented-audio-generation-claim-false', severity='MEDIUM' if test else 'HIGH', message='Documented capability lacks production source evidence.'))
    if negative and production:
        findings.append(dict(rule='documented-no-audio-generation-claim-false', severity='HIGH', message='Production source contradicts the documented absence.'))
    return dict(verdict='FAIL' if findings else 'PASS', findings=findings, files_scanned=count)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage()
        self.exit(1, self.prog + ': error: ' + message + '\n')


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument('root')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--ignore', action='append', default=[])
    parser.add_argument('--fail-on', choices=['HIGH', 'MEDIUM'], default='HIGH')
    parser.add_argument('--version', action='version', version=__version__)
    args = parser.parse_args(argv)
    try:
        result = audit(args.root, args.ignore)
    except (OSError, UnicodeError, ValueError) as error:
        parser.exit(1, str(error) + '\n')
    if args.json:
        print(json.dumps(result))
    else:
        print(result['verdict'])
        for finding in result['findings']:
            print('{severity} {rule}: {message}'.format(**finding))
        if args.verbose:
            print('Files scanned: {}'.format(result['files_scanned']))
    return 2 if any(f['severity'] == 'HIGH' or args.fail_on == 'MEDIUM' for f in result['findings']) else 0
