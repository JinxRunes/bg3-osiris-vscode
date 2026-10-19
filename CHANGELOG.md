# Changelog

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
