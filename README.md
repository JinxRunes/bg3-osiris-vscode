# Baldur's Gate 3 Osiris for VS Code

A BG3-focused fork of [Sebastian Lenz's Divinity Engine Script Support](https://github.com/sebastian-lenz/divinity-vscode), under the original MIT license.

## Features

- Osiris goal, definition and log highlighting, plus snippets.
- BG3 completion, parameter hints, hover, go to definition, references and document symbols.
- API signatures and enum members read from your project's generated `story_header.div`.
- Dependency procedures indexed from the Toolkit's `goals.raw` snapshot.
- Live syntax diagnostics, including BG3 enum literals such as `ARMOURSET.Normal`.
- A Story Goals tree following parent relationships between mod-owned goals.
- **BG3 Osiris: Prepare Project from Toolkit Build** and **BG3 Osiris: Build Story** commands.
- A build task available with **Ctrl+Shift+B**. Native compiler errors appear in Problems.
- Real `story.div.osi` output, compiled by your installed Toolkit's native compiler.

## Requirements

Editing works in desktop VS Code 1.85 or newer. Native compilation additionally requires Windows x64, Python 3.10+, the .NET 10 runtime, and an installed BG3 Toolkit.

The compiler host currently supports the inspected `Osiris.dll` with SHA-256:

```text
340d688aca31cc399c4639529a3381f1a7e57e489d7501dbc337eff90a91e6fc
```

A different DLL is rejected. Supporting another Toolkit build requires checking the compiler ABI and serializer before adding its identity. The game DLL is read from your installation and is never included in this extension.

## First build

1. Install the `.vsix` with **Extensions: Install from VSIX**. Disable the original Divinity extension for this workspace if installed; both use its language IDs for compatibility.
2. Open your module folder: `Data/Mods/YourModule_UUID`, containing `Story/RawFiles/Goals`.
3. Set **BG3 Osiris: Toolkit Path** to the directory containing the Toolkit's `Osiris.dll`.
4. In the Toolkit, generate definitions and complete one successful Story build for this module.
5. Run **BG3 Osiris: Prepare Project from Toolkit Build**. This captures the dependency story, header, definitions and orphan-query settings into local extension storage.
6. Edit your goals, then run **BG3 Osiris: Build Story**, or use **Ctrl+Shift+B**.
7. Run **BG3 Osiris: Open Last Build Output** to find `story.div.osi`, its input files, compiler log and JSON report.

Builds are staged in VS Code's extension storage. They do **not** install a story into the game, reload an editor session, or package a mod. Install the output through your normal mod workflow after reviewing the successful build. A failed build produces no usable `.osi`.

Set **BG3 Osiris: Project Path** explicitly when the workspace is outside the module folder. Build commands ask which module to use when several are available. The language service shares API symbols between modules in a multi-module workspace; use separate windows for modules with incompatible headers or conflicting custom symbols.

## What the compiler does

The backend preserves dependency goal blocks, order and activation relationships from a successful Toolkit build. It merges current mod-owned goal files, validates parent references and cycles, and runs the native compiler in a separate worker process. This provides native symbol resolution, type inference and BG3 enum support. Diagnostics are mapped to edited goal files where the compiler's source location is available.

Baseline hashes are checked before every build. Edits made before preparation are detected rather than silently replaced with old source. Compiler failures and process crashes leave the module's working story untouched.

After a Toolkit/game update, dependency changes, or changes requiring new generated object definitions, generate definitions and build in the Toolkit again, then run Prepare Project again. The previous baseline is archived beside the new one. A changed compiler still requires ABI verification before it is supported. This first version does not regenerate engine definitions itself.

The native compiler may refuse output even when it reports only warnings, such as an unchecked database. Those builds are reported as failed; fix the warnings before using the output.

Live diagnostics check syntax; native builds are the authority for types and dependency resolution. Runtime gameplay behavior still needs testing in the game or Toolkit.

## Command-line build

```powershell
python tools/bg3_osiris.py prepare --project "D:\BG3\Data\Mods\MyMod_UUID" --toolkit "D:\BG3 Toolkit" --state-dir "D:\Builds\MyMod"
python tools/bg3_osiris.py build --project "D:\BG3\Data\Mods\MyMod_UUID" --toolkit "D:\BG3 Toolkit" --state-dir "D:\Builds\MyMod"
```

Build storage contains local game-derived data. Keep it out of source control and distributable mod packages. No game assets, story headers, dependency story snapshots or compiled game stories are shipped in the VSIX.

## Development

```text
npm ci
npm run check
npm run compile
npm test
npm run build:native
npm run package
```

Building the worker from source requires the .NET 10 SDK. The packaged extension needs only the runtime.

Run native integration tests against a module with a successful Toolkit build:

```powershell
python tools/test_bg3_osiris.py --project "D:\BG3\Data\Mods\MyMod_UUID" --toolkit "D:\BG3 Toolkit"
```

Tests copy module inputs into temporary local storage. They compare the output with the Toolkit binary excluding its timestamp, compile a new BG3 enum goal, reject an invalid procedure and check its diagnostic location, and verify edits made before preparation are retained. Test stories are never installed.

The `bg3-osiris-local` publisher identifier is for local packages. Choose an owned publisher and fork repository before public Marketplace publication.

## Attribution and scope

The original extension's license, grammars, snippets and syntax parser are retained. The parser used by the new service is isolated in `src/bg3/parser`; upstream DOS2 sources remain for reference. The new service and commands do not run the original DOS2 tool downloader, debugger installer or reload commands.

This first BG3 version focuses on Osiris editing and native compilation. The old API Explorer webview, semantic rename, DOS2 debugger and automatic runtime reload are not advertised as BG3 features. API links open the official BG3 modding documentation.
