"""BG3 native story build backend. Game-derived inputs stay in local build storage."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
import story_install

NATIVE_SHA = '340d688aca31cc399c4639529a3381f1a7e57e489d7501dbc337eff90a91e6fc'
COMPILE_SUMMARY = re.compile(r'(\d+) error\(s\),\s*(\d+) warning\(s\)\. Compilation ended\.')
VALID_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,119}\Z')
SEED_FILES = ['goals.raw', 'story_header.div', 'story_definitions.div', 'story_orphanqueries_ignore.txt']
TOOLKIT = Path('.')
STORY = Path('.')
GOALS = Path('.')
ROOT = Path('.')
CACHE = Path('.')
BUILDS = Path('.')
BACKUPS = Path('.')
NATIVE = Path('.')
WORKER = Path(__file__).parent / 'native-worker/out/NativeOsirisWorker.dll'
DOTNET = 'dotnet'
MODULE = ''

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def stamp(): return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]

def read_text(path): return Path(path).read_text(encoding='utf-8-sig')

def write_text(path,text):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(text.replace('\r\n','\n').replace('\r','\n').replace('\n','\r\n').encode('utf-8'))

def json_write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')

def source_sections(text):
    text=text.replace('\r\n','\n')
    markers=list(re.finditer(r'^(INITSECTION|KBSECTION|EXITSECTION|ENDEXITSECTION)\s*$',text,re.M))
    if [m.group(1) for m in markers]!=['INITSECTION','KBSECTION','EXITSECTION','ENDEXITSECTION']:
        raise ValueError('Expected exactly one INIT, KB and EXIT section, in that order.')
    combiner=re.search(r'^SubGoalCombiner\s+(\w+)',text,re.M)
    if combiner is None or combiner.group(1)!='SGC_AND':
        raise ValueError('This version supports the native Story Editor SGC_AND goal layout.')
    sections={key:text[markers[i].end():markers[i+1].start()].strip('\n') for i,key in enumerate(['INIT','KB','EXIT'])}
    parents=re.findall(r'^ParentTargetEdge\s+"([^"]+)"',text,re.M)
    return sections,parents

def parse_raw(text):
    titles={int(i):name for i,name in re.findall(r'^Goal\((\d+)\)\.Title\("([^"\n]+)"\);',text,re.M)}
    blocks={int(m.group(1)):m.group(0) for m in re.finditer(r'^Goal\((\d+)\)\n\{\n.*?^\}',text,re.M|re.S)}
    if not titles or titles.keys()!=blocks.keys() or len(titles.values())!=len(set(titles.values())):
        raise ValueError('Unrecognised or ambiguous native goals.raw layout.')
    records={name:{'id':i,'block':blocks[i]} for i,name in titles.items()}
    edges=[(titles[int(a)],titles[int(b)]) for a,b in re.findall(r'^Goal\((\d+)\)\.SubGoal\((\d+)\);',text,re.M)]
    combiners=[titles[int(i)] for i in re.findall(r'^Goal\((\d+)\)\.SubGoals\(AND\);',text,re.M)]
    version=re.search(r'^version "[^"]+"',text,re.M).group(0)
    return version,records,edges,combiners

def goal_paths(directory=None):
    directory = GOALS if directory is None else directory
    return {p.stem:p for p in sorted(Path(directory).glob('*.txt'))}

def seed():
    log=read_text(STORY/'log.txt')
    summary=COMPILE_SUMMARY.findall(log)
    if not summary or summary[-1][0]!='0': raise RuntimeError('Seed requires a successful native Toolkit build.')
    parse_raw(read_text(STORY/'goals.raw'))
    source_files={name:STORY/('RawFiles/'+name if name in ['story_header.div','story_definitions.div'] else name) for name in SEED_FILES}
    for source in source_files.values():
        if not source.exists(): raise FileNotFoundError(str(source))
    # Draft goals must not prevent capturing the last successful Toolkit build.
    # Publish only a complete snapshot; a failed refresh leaves the previous one usable.
    preparing=CACHE.with_name(CACHE.name+'.preparing-'+stamp())
    assert preparing.resolve().is_relative_to(ROOT.resolve())
    preparing.mkdir(parents=True)
    try:
        for name in SEED_FILES: shutil.copy2(source_files[name],preparing/name)
        own=goal_paths()
        snapshots={}
        for name,path in own.items():
            dest=preparing/'own-goals'/path.name;dest.parent.mkdir(exist_ok=True);shutil.copy2(path,dest)
            snapshots[name]=dest
        _, raw_records, _, _ = parse_raw(read_text(preparing/'goals.raw'))
        uncompiled = []
        drafts = {}
        for name, path in snapshots.items():
            native_sections = dict(re.findall(r'^\t(INIT|KB|EXIT)\n\t\{\n(.*?)^\t\}',
                                             raw_records.get(name, {}).get('block', ''), re.M | re.S))
            try:
                current_sections, _ = source_sections(read_text(path))
            except ValueError as error:
                drafts[name]=str(error)
                uncompiled.append(name)
                continue
            if name not in raw_records or any(section_fingerprint(native_sections.get(key, '')) != section_fingerprint(value)
                   for key, value in current_sections.items()):
                uncompiled.append(name)
        metadata={'module':MODULE,'created_at':datetime.now(timezone.utc).isoformat(),
                  'native_sha256':NATIVE_SHA,'toolkit_build_summary':list(summary[-1]),
                  'files':{name:sha(preparing/name) for name in SEED_FILES},
                  'own_goals':{name:sha(path) for name,path in snapshots.items()},
                  'uncompiled_goals':uncompiled, 'draft_goals':drafts,
                  'toolkit_osi_sha256':sha(STORY/'story.div.osi')}
        json_write(preparing/'seed.json',metadata)
        archived=None
        if CACHE.exists():
            archived=CACHE.with_name(CACHE.name+'.previous-'+stamp())
            assert CACHE.resolve().is_relative_to(ROOT.resolve()) and archived.resolve().is_relative_to(ROOT.resolve())
            CACHE.rename(archived)
        try:
            preparing.rename(CACHE)
        except OSError:
            if archived is not None: archived.rename(CACHE)
            raise
        return metadata
    finally:
        if preparing.exists():
            assert preparing.resolve().is_relative_to(ROOT.resolve())
            shutil.rmtree(preparing)

def baseline():
    if not (CACHE/'seed.json').exists():
        raise RuntimeError('No completed preparation was found for '+MODULE+'. Run "BG3 Osiris: Prepare Project from Toolkit Build" '
                           'and check that it finishes successfully. Expected baseline: '+str(CACHE))
    m=json.loads((CACHE/'seed.json').read_text())
    for name,digest in m['files'].items():
        if sha(CACHE/name)!=digest: raise RuntimeError(f'Baseline changed: {name}')
    return m

@contextmanager
def locked():
    ROOT.mkdir(parents=True,exist_ok=True)
    lock=ROOT/'build.lock'
    # OS locks are released even if a VS Code task is cancelled or a process crashes.
    # Keep the file in place: unlinking a locked file introduces a competing-builder race.
    with lock.open('a+b') as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b' ')
            handle.flush()
        handle.seek(0)
        try:
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError('Another BG3 build is running for this project.') from error
        try:
            handle.seek(0)
            handle.write(str(os.getpid()).encode('ascii'))
            handle.truncate()
            handle.flush()
            yield
        finally:
            handle.seek(0)
            if sys.platform == 'win32':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

def assemble(directory,own_directory=None):
    own_directory = GOALS if own_directory is None else own_directory
    m=baseline();version,records,edges,combiners=parse_raw(read_text(CACHE/'goals.raw'))
    own=goal_paths(own_directory)
    removed=set(m['own_goals'])-set(own)
    for name in removed: records.pop(name,None)
    edges=[(a,b) for a,b in edges if a not in removed and b not in removed]
    mapping={}
    for name,path in own.items():
        if not VALID_NAME.fullmatch(name): raise ValueError(f'Unsupported goal filename: {path.name}')
        result=preflight_source(path)
        if not result['syntax_ok']: raise ValueError(f'{path.name}: {result["output"]}')
        if name in records and name not in m['own_goals']:
            raise ValueError(f'{name} conflicts with a dependency goal.')
        sections,parents=source_sections(read_text(path))
        original=records.get(name)
        # Keep unchanged native blocks byte-for-byte, while detecting edits that
        # were already present when the dependency baseline was captured.
        changed=not original or sha(path)!=m['own_goals'].get(name) or name in m.get('uncompiled_goals', [])
        if changed:
            body='Goal(0)\n{\n'
            spans={}
            for section,content in sections.items():
                body+=f'\t{section}\n\t{{\n'
                start=body.count('\n')+1
                body+=''.join('\t\t'+line+'\n' for line in content.split('\n'))
                original_source = read_text(path)
                marker = re.search(r'^' + section + r'SECTION\s*$', original_source, re.M)
                spans[section]={'block_start_line':start,
                                'source_start_line':original_source.count('\n', 0, marker.end()) + 1}
                body+='\t}\n'
            body+='}'
            records[name]={'id':original['id'] if original else max((r['id'] for r in records.values()),default=0)+1,'block':body}
            mapping[name]={'file':str(path.resolve()),'sections':spans}
        edges=[(a,b) for a,b in edges if b!=name]
        edges.extend((parent,name) for parent in parents)
    names=sorted(records,key=lambda n:records[n]['id'])
    ids={name:i+1 for i,name in enumerate(names)}
    for parent,child in edges:
        if parent not in ids or child not in ids: raise ValueError(f'Unknown parent/child goal: {parent} -> {child}')
    # Reject cycles before passing a new activation graph into the native compiler.
    children={name:[] for name in names}
    for parent,child in edges: children[parent].append(child)
    visiting=set();visited=set()
    def visit(name):
        if name in visiting: raise ValueError('Cycle in goal activation graph: '+name)
        if name in visited:return
        visiting.add(name)
        for next_name in children[name]: visit(next_name)
        visiting.remove(name);visited.add(name)
    for name in names:visit(name)
    chunks=[version+'\n'];line_count=1
    source_map=[]
    for name in names:
        block=re.sub(r'^Goal\(\d+\)',f'Goal({ids[name]})',records[name]['block'],count=1)
        chunks.append(f'Goal({ids[name]}).Title("{name}");\n')
        line_count+=1
        source_map.append({'goal':name,'id':ids[name],'goals_raw_start_line':line_count+1,'goals_raw_end_line':line_count+block.count('\n')+1,
                           'source':str(own[name]) if name in own else 'Toolkit baseline'})
        chunks.append(block+'\n');line_count+=block.count('\n')+1
    # Preserve native ordering for dependency edges and combiner declarations.
    for parent,child in edges: chunks.append(f'Goal({ids[parent]}).SubGoal({ids[child]});\n')
    for name in dict.fromkeys(combiners+[child for _,child in edges if child in own]):
        if name in ids: chunks.append(f'Goal({ids[name]}).SubGoals(AND);\n')
    raw=''.join(chunks)
    write_text(directory/'goals.raw',raw)
    # Native content publication can refresh definitions without rebuilding story.
    # Keep the immutable dependency seed, but compile the current native headers.
    header_file=STORY/'RawFiles/story_header.div'
    definitions_file=STORY/'RawFiles/story_definitions.div'
    if not header_file.is_file():header_file=CACHE/'story_header.div'
    if not definitions_file.is_file():definitions_file=CACHE/'story_definitions.div'
    header=read_text(header_file);definitions=read_text(definitions_file)
    write_text(directory/'story.div',header+'\n'+definitions+'\n'+raw+'\n')
    for name in SEED_FILES[1:]: shutil.copy2(CACHE/name,directory/name)
    shutil.copy2(header_file,directory/'story_header.div');shutil.copy2(definitions_file,directory/'story_definitions.div')
    json_write(directory/'source-map.json',{'header_lines':header.count('\n')+1+definitions.count('\n')+1,
               'goals':source_map,'changed_goal_sections':mapping})
    return {name:sha(path) for name,path in own.items()}

def compile_build(install=False,own_directory=None,tag=None):
    own_directory = GOALS if own_directory is None else own_directory
    ensure_tools();directory=BUILDS/(stamp()+('-'+tag if tag else ''));directory.mkdir(parents=True)
    before_inputs=story_install.inventory(STORY.parent) if install else None
    before_outputs=story_install.working_hashes(STORY.parent) if install else None
    sources=assemble(directory,own_directory)
    # Snapshot the known-good artifact before compiling, for exact failure checks.
    deployed_before=sha(STORY/'story.div.osi') if (STORY/'story.div.osi').exists() else None
    run=subprocess.run([DOTNET,str(WORKER),str(NATIVE),NATIVE_SHA,str(directory/'story.div'),
                         str(directory/'story.div.osi'),str(directory/'log.txt')],
                        capture_output=True,text=True,timeout=180)
    log=read_text(directory/'log.txt') if (directory/'log.txt').exists() else ''
    summaries=COMPILE_SUMMARY.findall(log)
    errors,warnings=map(int,summaries[-1]) if summaries else (None,None)
    osi=directory/'story.div.osi'
    success=run.returncode==0 and errors==0 and osi.exists() and osi.stat().st_size>256
    if success and not osi.read_bytes()[:64].startswith(b'\x00Osiris save file dd.'):
        success=False
    report={'success':success,'errors':errors,'warnings':warnings,'build':str(directory),
            'native_compiler_sha256':NATIVE_SHA,'source_sha256':sources,'installed':False,
            'compiled_osi_sha256':sha(osi) if osi.exists() else None,
            'stdout':run.stdout.strip(),'stderr':run.stderr.strip(),
            'diagnostic_tail':log[-6000:] if not success else None}
    if not success and errors == 0 and warnings:
        report['error'] = f'The native compiler rejected this build with {warnings} warning(s). Resolve the reported warnings and build again.'
    diagnostics=[]
    for line,severity,message in re.findall(r'^line (\d+): (error|warning): (.+)$',log,re.M):
        candidates=[]
        symbol=(re.search(r'(?:procedure|function|query) "([^"]+)"',message)
                or re.search(r'Osiris fact/proc/query ([A-Za-z_]\w*)\b',message))
        if symbol:
            for path in goal_paths(own_directory).values():
                for number,source_line in enumerate(read_text(path).splitlines(),1):
                    if re.search(r'\b'+re.escape(symbol.group(1))+r'\s*\(',source_line):
                        candidates.append({'file':str(path),'line':number})
        diagnostics.append({'compiler_line':int(line),'severity':severity,'message':message,'source_candidates':candidates})
    report['diagnostics']=diagnostics
    if install:
        if own_directory!=GOALS: raise RuntimeError('Only the real active module can be installed.')
        story_install.install(STORY.parent,directory,report,before_inputs,before_outputs)
        if report.get('installed'): json_write(ROOT/'last-installed.json',report)
    report['working_osi_unchanged']=((sha(STORY/'story.div.osi') if (STORY/'story.div.osi').exists() else None)==deployed_before)
    json_write(directory/'report.json',report)
    json_write(ROOT/'last-build.json',report)
    return report


def configure(project, toolkit, state_dir=None, dotnet='dotnet'):
    global TOOLKIT, STORY, GOALS, ROOT, CACHE, BUILDS, BACKUPS, NATIVE, DOTNET, MODULE
    project = Path(project).resolve()
    TOOLKIT = Path(toolkit).resolve()
    STORY = project / 'Story'
    GOALS = STORY / 'RawFiles/Goals'
    if not GOALS.is_dir():
        raise ValueError('Select a BG3 module folder containing Story/RawFiles/Goals.')
    MODULE = project.name
    ROOT = Path(state_dir).resolve() if state_dir else project / '.bg3-osiris'
    if ROOT == project or ROOT == STORY or ROOT == GOALS:
        raise ValueError('Build storage must be a separate subfolder or external folder.')
    CACHE = ROOT / 'baseline'
    BUILDS = ROOT / 'builds'
    BACKUPS = ROOT / 'backups'
    NATIVE = TOOLKIT / 'Osiris.dll'
    DOTNET = dotnet


def section_fingerprint(text):
    return re.sub(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:[^"\\]|\\.)*"|\s+',
                  lambda match: match.group(0) if match.group(0).startswith('"') else '', text)


def ensure_tools():
    if sys.platform != 'win32':
        raise RuntimeError('Native BG3 compilation currently requires Windows x64.')
    if not NATIVE.is_file() or sha(NATIVE) != NATIVE_SHA:
        raise RuntimeError('Unsupported Toolkit Osiris.dll. This build supports SHA-256 ' + NATIVE_SHA +
                           '. A different compiler needs ABI verification; the version guard cannot be bypassed.')
    if not WORKER.is_file():
        raise RuntimeError('Compiler worker is missing. Run npm run build:native when building from source.')


def preflight_source(path):
    # This checks the file envelope only. Native compilation is the syntax/type authority.
    try: source_sections(read_text(path))
    except ValueError as error: raise ValueError(str(path)+': '+str(error)) from error
    return {'syntax_ok': True}


def locate_diagnostics(report):
    mapping = json.loads((Path(report['build']) / 'source-map.json').read_text())
    for diagnostic in report['diagnostics']:
        # Native error lines can point at whitespace preceding the failing call.
        # A unique symbol occurrence gives a more useful location in that case.
        candidates = diagnostic.get('source_candidates', [])
        if len(candidates) == 1:
            candidate = candidates[0]
            diagnostic.update(file=candidate['file'], line=candidate['line'], column=1, approximate=True)
            continue
        raw_line = diagnostic['compiler_line'] - mapping['header_lines']
        for goal in mapping['goals']:
            if not goal['goals_raw_start_line'] <= raw_line <= goal['goals_raw_end_line']:
                continue
            sections = mapping['changed_goal_sections'].get(goal['goal'])
            if sections:
                block_line = raw_line - goal['goals_raw_start_line'] + 1
                spans = [s for s in sections['sections'].values() if s['block_start_line'] <= block_line]
                if spans:
                    span = max(spans, key=lambda s: s['block_start_line'])
                    diagnostic['file'] = sections['file']
                    source_lines = read_text(sections['file']).splitlines()
                    diagnostic['line'] = min(len(source_lines), max(1, span['source_start_line'] + block_line - span['block_start_line']))
                    diagnostic['column'] = 1
            break
        # Symbol-based candidates remain explicitly approximate, never claimed as exact locations.
        if 'file' not in diagnostic and len(diagnostic.get('source_candidates', [])) == 1:
            candidate = diagnostic['source_candidates'][0]
            diagnostic.update(file=candidate['file'], line=candidate['line'], column=1, approximate=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'build', 'status', 'rollback'])
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--toolkit', required=True, type=Path)
    parser.add_argument('--state-dir', type=Path)
    parser.add_argument('--dotnet', default='dotnet')
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--prepare-if-needed', action='store_true')
    args = parser.parse_args()
    configure(args.project, args.toolkit, args.state_dir, args.dotnet)
    ensure_tools()
    if args.install and args.action != 'build':
        raise ValueError('Only a successful build can be installed.')
    if args.action == 'rollback':
        latest=json.loads((ROOT/('last-installed.json' if (ROOT/'last-installed.json').is_file() else 'last-build.json')).read_text(encoding='utf-8'))
        folder=Path(latest['build']).resolve()
        if not folder.is_relative_to(BUILDS.resolve()): raise ValueError('The last build is outside this project build store.')
        result=story_install.rollback(STORY.parent,folder)
        print('BG3_RESULT '+json.dumps(result),flush=True)
        return 0
    if args.action == 'status':
        result = {'success': True, 'module': MODULE, 'prepared': (CACHE / 'seed.json').is_file(),
                  'native_compiler_sha256': NATIVE_SHA, 'state_dir': str(ROOT)}
    else:
        with locked():
            if args.action == 'prepare':
                print('Capturing dependency inputs from the last successful Toolkit build...', flush=True)
                result = {'success': True, 'baseline': str(CACHE), 'seed': seed()}
                for name, message in result['seed']['draft_goals'].items():
                    print(f'Prepared dependencies; draft goal {name}.txt must be completed before building: {message}', flush=True)
            else:
                if args.prepare_if_needed and not (CACHE/'seed.json').is_file(): seed()
                baseline()
                inputs=story_install.inventory(STORY.parent)
                outputs=story_install.working_hashes(STORY.parent)
                print('Compiling BG3 story with the installed native compiler...', flush=True)
                result = compile_build()
                locate_diagnostics(result)
                current = {name: sha(path) for name, path in goal_paths().items()}
                if current != result['source_sha256']:
                    result.update(success=False, error='Goal sources changed during compilation. Build again.')
                result['input_sha256']=inputs
                if args.install:
                    story_install.install(STORY.parent,Path(result['build']),result,inputs,outputs)
                    if result.get('installed'): json_write(ROOT/'last-installed.json',result)
                json_write(Path(result['build']) / 'report.json', result)
                json_write(ROOT / 'last-build.json', result)
                for item in result['diagnostics']:
                    if item.get('file'):
                        print(f"{item['severity']}: {item['file']}({item['line']},1): {item['message']}", flush=True)
                print('Build succeeded.' if result['success'] else 'Build failed.', flush=True)
                if result.get('build'):
                    print('Output: ' + result['build'], flush=True)
    print('BG3_RESULT ' + json.dumps(result), flush=True)
    return 0 if result['success'] else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, OSError, KeyError, subprocess.TimeoutExpired) as error:
        print('BG3_RESULT ' + json.dumps({'success': False, 'error': str(error)}), flush=True)
        sys.exit(1)
