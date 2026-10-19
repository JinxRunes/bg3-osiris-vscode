"""Toolkit-independent checks/builds using an externally installed OsiCheck library."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import bg3_osiris as shared

DEFAULT_MODS = ['Shared', 'SharedDev', 'Gustav', 'GustavDev', 'GustavX', 'Honour', 'HonourX']
DEFAULT_EXEMPTIONS = ['DB_BUGFIX_Marker(4)', 'DB_BUGFIX_Marker_GUS309397(3)',
                      'DB_Hirelings_DialogFlagsVars(5)', 'DB_BUGFIX_Marker_GUSX9096(2)']
WORKER = Path(__file__).parent / 'osicheck-worker/out/OsiCheckWorker.dll'


def library_dir(value):
    path = Path(value).expanduser().resolve()
    if path.is_file(): path = path.parent
    if (path / 'bin/LSLib.dll').is_file(): path = path / 'bin'
    if not (path / 'LSLib.dll').is_file() or not (path / 'StoryCompiler.dll').is_file():
        raise ValueError('Set BG3 Osiris: OsiCheck Path to the supplied OsiCheck folder or its bin folder.')
    return path


def game_data(project, configured=''):
    candidates = []
    if configured:
        path = Path(configured).expanduser().resolve()
        candidates = [path, path / 'Data']
    else:
        candidates = list(Path(project).resolve().parents)
        if sys.platform == 'win32':
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as key:
                    steam = Path(winreg.QueryValueEx(key, 'SteamPath')[0])
                libraries = [steam]
                vdf = steam / 'steamapps/libraryfolders.vdf'
                if vdf.is_file():
                    libraries += [Path(value.replace('\\\\', '\\')) for value in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text())]
                candidates += [root / 'steamapps/common/Baldurs Gate 3/Data' for root in libraries]
            except (OSError, ValueError): pass
    for path in candidates:
        if (path / 'Shared.pak').is_file() and (path / 'Localization').is_dir(): return path
    raise ValueError('Set BG3 Osiris: Game Data Path to the game Data folder containing Shared.pak. A Toolkit installation is not required.')


def run(action, project, osicheck_path, state_dir, data_path='', dotnet='dotnet', base_mods=None, exemptions=None, package_only=False):
    if action not in ['check', 'build']: raise ValueError('OsiCheck supports check and build actions.')
    project = Path(project).resolve()
    libraries = library_dir(osicheck_path)
    data = game_data(project, data_path)
    # Shared locking and storage helpers do not load or require a Toolkit DLL.
    shared.configure(project, project, state_dir, dotnet)
    if not WORKER.is_file(): raise RuntimeError('OsiCheck worker is missing; rebuild the extension package.')
    mods = DEFAULT_MODS if base_mods is None else base_mods
    known = DEFAULT_EXEMPTIONS if exemptions is None else exemptions
    with shared.locked():
        directory = shared.BUILDS / (shared.stamp() + '-osicheck-' + action)
        directory.mkdir(parents=True)
        request = {'libraryDir':str(libraries), 'gameDataPath':str(data), 'projectPath':str(project),
                   'outputDir':str(directory), 'action':action, 'baseMods':mods, 'knownVanillaIssues':known, 'packageOnly':package_only}
        shared.json_write(directory / 'request.json', request)
        print(f'BG3 Osiris: {action} with OsiCheck (no Toolkit preparation required).', flush=True)
        completed = subprocess.run([dotnet, '--roll-forward', 'Major', str(WORKER), str(directory / 'request.json')],
                                   capture_output=True, text=True, timeout=240)
        shared.write_text(directory / 'compiler.stdout.txt', completed.stdout)
        shared.write_text(directory / 'compiler.stderr.txt', completed.stderr)
        try:
            report = json.loads(completed.stdout.strip())
        except (ValueError, TypeError):
            report = {'success':False, 'diagnostics':[],
                      'error':'OsiCheck worker failed: ' + (completed.stderr or completed.stdout or f'exit code {completed.returncode}')[-4000:]}
        report.update(build=str(directory), action=action, compiler='osicheck', installed=False,
                      compiler_sha256=shared.sha(libraries / 'LSLib.dll'))
        report['success'] = completed.returncode == 0 and report.get('success', False)
        # LSLib reports unused/misnamed database symbols without source locations.
        # Map their first use in the frozen project snapshot back to the editor.
        for item in report.get('diagnostics', []):
            if item.get('file') or item.get('code') not in ['E25','W26']: continue
            symbol=re.search(r'database "([A-Za-z_]\w*)(?:\(\d+\))?"',item.get('message',''),re.I)
            if not symbol: continue
            for frozen in sorted((directory/'inputs/Mods'/project.name/'Story/RawFiles/Goals').glob('*.txt')):
                lines=shared.read_text(frozen).splitlines()
                found=next(((row,line) for row,line in enumerate(lines,1) if re.search(r'\b'+re.escape(symbol[1])+r'\s*\(',line)),None)
                if found:
                    item.update(file=str(shared.GOALS/frozen.name),line=found[0],column=1,approximate=True)
                    break
        current = {name:shared.sha(path) for name,path in shared.goal_paths().items()}
        if report.get('source_sha256') is not None and current != report['source_sha256']:
            report.update(success=False, error='Goal sources changed during checking or compilation. Run the command again.')
        output = directory / 'story.div.osi'
        if action == 'build' and report['success']:
            if not output.is_file() or not output.read_bytes()[:64].startswith(b'\x00Osiris save file dd.'):
                report.update(success=False, error='OsiCheck did not produce a valid story file.')
        if not report['success']:
            for artifact in [output, directory / 'story.div.osi.partial']:
                if artifact.exists():
                    assert artifact.resolve().is_relative_to(directory.resolve())
                    artifact.unlink()
        report['compiled_osi_sha256'] = shared.sha(output) if output.is_file() else None
        header=directory/'story_header.div'
        if report.get('header_file') and header.is_file():
            cached=shared.ROOT/'osicheck-api-header.div'
            shutil.copy2(header,cached)
            report['header_file']=str(cached)
        shared.json_write(directory / 'report.json', report)
        shared.json_write(shared.ROOT / ('last-check.json' if action == 'check' else 'last-build.json'), report)
        for item in report.get('diagnostics', []):
            if item.get('file'):
                print(f"{item['severity']}: {item['file']}({item.get('line') or 1},{item.get('column') or 1}): [{item.get('code', '')}] {item['message']}", flush=True)
            else: print(f"{item['severity']}: [{item.get('code', '')}] {item['message']}", flush=True)
        if report.get('known_vanilla_exemptions'):
            print('Exact vanilla unused-database exemptions: ' + ', '.join(report['known_vanilla_exemptions']), flush=True)
        print(('Check' if action == 'check' else 'Build') + (' succeeded.' if report['success'] else ' failed.'), flush=True)
        print('Output: ' + str(directory), flush=True)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'build'])
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--osicheck', required=True)
    parser.add_argument('--state-dir', required=True, type=Path)
    parser.add_argument('--game-data', default='')
    parser.add_argument('--dotnet', default='dotnet')
    parser.add_argument('--base-mods', type=json.loads, default=DEFAULT_MODS)
    parser.add_argument('--known-vanilla-issues', type=json.loads, default=DEFAULT_EXEMPTIONS)
    parser.add_argument('--packages-only', action='store_true', help='Load dependencies from game packages only; still load the selected project sources.')
    args = parser.parse_args()
    for values in [args.base_mods, args.known_vanilla_issues]:
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError('Dependency modules and known vanilla issues must be arrays of strings.')
    result = run(args.action, args.project, args.osicheck, args.state_dir, args.game_data, args.dotnet,
                 args.base_mods, args.known_vanilla_issues, args.packages_only)
    print('BG3_RESULT ' + json.dumps(result), flush=True)
    return 0 if result['success'] else 1


if __name__ == '__main__':
    try: sys.exit(main())
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as error:
        print('BG3_RESULT ' + json.dumps({'success':False, 'error':str(error)}), flush=True)
        sys.exit(1)
