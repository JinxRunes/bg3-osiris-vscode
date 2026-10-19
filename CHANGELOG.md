# Changelog

## 0.4.0

- Prepare the public Marketplace release under publisher `jinx` and link the JinxRunes source repository and issue tracker.

## 0.3.0

- Add Build and Install Story with source/output conflict checks, installation backups and recoverable story rollback.
- Add Update Game Content (Jinx Tools): save files, start the local authoring service, launch the shared project update and show progress.
- Share both compiler backends with the authoring pipeline without requiring the Story Editor.
- Automatically prepare native dependencies from an existing successful native baseline when needed; use current project headers and definitions.
- Preserve staged behavior for ordinary Build Story and preserve the last installed receipt after later failed builds.

## 0.2.0

- Add OsiCheck check/build commands and task selection without loading the Toolkit compiler or requiring a preparation step.
- Resolve the compiler from a separately installed OsiCheck folder and load extracted dependency headers and goals alongside game packages.
- Reject retail packages alone with an explanation of the missing source inputs; do not rebuild dependencies from lossy decompiled stories.
- Snapshot inputs, preserve ordinary compiler errors, and report exact vanilla database exemptions.
- Verify rule counts, global IFF links and enum table counts in saved stories before reporting success.
- Refresh API completion from the game header after standalone checks and builds.
- Retain the native Toolkit backend and existing preparation/storage workflow.

## 0.1.2

- Allow preparation with empty or unfinished goal files, marking drafts for compilation.
- Publish preparation snapshots atomically and preserve the previous baseline on failure.
- Name the source file in section errors and replace internal "Run seed" wording with the actual command.
- Support IFF in syntax checks, highlighting, completion and document symbols.
- Add native binary verification of IFF rule preservation and global goal references.

## 0.1.1

- Detect modules when opening Story, RawFiles, Goals or a goal file directly.
- Use the same module discovery for build commands, tasks and the language service.
- Explain missing goal sections with one actionable syntax diagnostic.
- Add regression coverage for subfolder workspaces and opening files without a workspace.

## 0.1.0

- Fork Divinity Engine Script Support for BG3 Osiris editing.
- Add project headers, current enum support, parameter hints and dependency indexing.
- Add isolated native Toolkit builds, staged output and source-mapped errors.
- Replace DOS2 build/install contributions with BG3 commands and tasks.
- Add parser, language-server and native compiler regression checks.
