import * as fs from 'node:fs';
import * as path from 'node:path';

export type CompilerBackend = 'osicheck' | 'toolkit';
export type CompilerAction = 'prepare' | 'check' | 'build';
interface CompilerSettings {
  action: CompilerAction; backend?: CompilerBackend; selected?: string;
  extension: string; project: string; state: string; toolkit?: string; osicheck?: string;
  gameData?: string; dotnet?: string; dependencies?: string[]; vanillaIssues?: string[];
}

export function compilerInvocation(settings: CompilerSettings): { backend: CompilerBackend; args: string[] } {
  const selected = settings.backend ?? settings.selected ?? 'auto';
  const backend: CompilerBackend = settings.action === 'check' ? 'osicheck' : settings.action === 'prepare' ? 'toolkit'
    : selected === 'auto' ? (settings.osicheck ? 'osicheck' : 'toolkit') : selected === 'osicheck' ? 'osicheck' : 'toolkit';
  const common = ['--project', settings.project, '--state-dir', settings.state, '--dotnet', settings.dotnet ?? 'dotnet'];
  if (backend === 'osicheck') {
    if (!settings.osicheck) throw new Error('Set BG3 Osiris: OsiCheck Path to your OsiCheck folder. This backend does not need the Toolkit.');
    return { backend, args: ['-u', path.join(settings.extension, 'tools/osicheck_backend.py'), settings.action,
      ...common, '--osicheck', settings.osicheck, '--game-data', settings.gameData ?? '',
      '--base-mods', JSON.stringify(settings.dependencies ?? ['Shared', 'SharedDev', 'Gustav', 'GustavDev', 'GustavX', 'Honour', 'HonourX']),
      '--known-vanilla-issues', JSON.stringify(settings.vanillaIssues ?? ['DB_BUGFIX_Marker(4)', 'DB_BUGFIX_Marker_GUS309397(3)', 'DB_Hirelings_DialogFlagsVars(5)', 'DB_BUGFIX_Marker_GUSX9096(2)'])] };
  }
  if (!settings.toolkit || !fs.existsSync(path.join(settings.toolkit, 'Osiris.dll')))
    throw new Error('Set OsiCheck Path for Toolkit-independent builds, or set Toolkit Path to the folder containing Osiris.dll.');
  return { backend, args: ['-u', path.join(settings.extension, 'tools/bg3_osiris.py'), settings.action,
    ...common, '--toolkit', settings.toolkit] };
}
