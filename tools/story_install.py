"""Shared, recoverable story installation for the extension and Jinx Tools."""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import os
import shutil
import tempfile
import uuid


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inventory(project):
    project = Path(project).resolve()
    raw = project / 'Story/RawFiles'
    files = sorted(p for p in raw.rglob('*') if p.is_file() and p.suffix.lower() in ('.txt', '.div'))
    if any(p.is_symlink() or not p.resolve().is_relative_to(raw.resolve()) for p in files):
        raise ValueError('Story inputs contain an external link.')
    return {str(p.relative_to(project)): sha(p) for p in files}


@contextmanager
def project_lock(project):
    folder = Path(tempfile.gettempdir()) / 'bg3-osiris-project-locks'
    folder.mkdir(exist_ok=True)
    key = hashlib.sha256(str(Path(project).resolve()).lower().encode()).hexdigest()
    with (folder / (key + '.lock')).open('a+b') as handle:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError('Another story installation is running for this mod.') from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def working_hashes(project):
    story = Path(project) / 'Story'
    return {name: sha(story / name) if (story / name).is_file() else None
            for name in ('story.div', 'goals.raw', 'log.txt', 'story.div.osi')}


def install(project, directory, report, before_inputs, before_outputs):
    project, directory = Path(project).resolve(), Path(directory).resolve()
    if not report.get('success'):
        return report
    artifact = directory / 'story.div.osi'
    if not artifact.is_file() or not artifact.read_bytes()[:64].startswith(b'\x00Osiris save file dd.'):
        raise ValueError('The compiler did not produce a valid story artifact.')
    if report.get('compiled_osi_sha256') != sha(artifact):
        raise ValueError('The staged story changed after compilation.')
    with project_lock(project):
        if inventory(project) != before_inputs:
            raise RuntimeError('Saved story inputs changed during compilation. No story was installed.')
        if working_hashes(project) != before_outputs:
            raise RuntimeError('Another build changed the working story. No story was installed.')
        names = [name for name in ('story.div', 'goals.raw', 'log.txt', 'story.div.osi') if (directory / name).is_file()]
        backup = directory / 'before-install'
        backup.mkdir(exist_ok=False)
        for name in names:
            target = project / 'Story' / name
            if target.is_file():
                shutil.copy2(target, backup / name)
        receipt = {'project': str(project), 'status': 'prepared', 'before': before_outputs,
                   'after': {name: sha(directory / name) for name in names}, 'files': names}
        receipt_path = directory / 'installation.json'
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        completed = []
        try:
            # The executable story is installed last.
            for name in names:
                target = project / 'Story' / name
                temporary = target.with_name(target.name + '.' + uuid.uuid4().hex + '.tmp')
                try:
                    shutil.copy2(directory / name, temporary)
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
                completed.append(name)
        except OSError:
            for name in reversed(completed):
                target = project / 'Story' / name
                if before_outputs[name] is None:
                    target.unlink(missing_ok=True)
                else:
                    shutil.copy2(backup / name, target)
            receipt['status'] = 'restored-after-failure'
            receipt_path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
            raise
        receipt['status'] = 'installed'
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        report.update(installed=True, backup=str(backup), installed_hashes=receipt['after'],
                      previous_hashes=before_outputs, installation=str(receipt_path))
        return report


def rollback(project, directory):
    project, directory = Path(project).resolve(), Path(directory).resolve()
    path = directory / 'installation.json'
    receipt = json.loads(path.read_text(encoding='utf-8'))
    if receipt['project'] != str(project) or receipt['status'] != 'installed':
        raise ValueError('Choose an installed build for this exact mod.')
    with project_lock(project):
        if any(not (project / 'Story' / name).is_file() or sha(project / 'Story' / name) != value
               for name, value in receipt['after'].items()):
            raise RuntimeError('A later build or editor change prevents rollback. The backup was preserved.')
        for name in receipt['files']:
            backup = directory / 'before-install' / name
            if receipt['before'][name] is not None and (not backup.is_file() or sha(backup) != receipt['before'][name]):
                raise ValueError('The installation backup changed. No rollback was performed.')
        for name in receipt['files']:
            target = project / 'Story' / name
            if receipt['before'][name] is None:
                target.unlink()
            else:
                temporary = target.with_name(target.name + '.rollback.tmp')
                shutil.copy2(directory / 'before-install' / name, temporary)
                os.replace(temporary, target)
        receipt['status'] = 'rolled-back'
        path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        return {'success': True, 'rolledBack': True, 'build': str(directory)}
