# Baldur's Gate 3 Osiris for VS Code

A BG3-focused fork of [Sebastian Lenz's Divinity Engine Script Support](https://github.com/sebastian-lenz/divinity-vscode), under the original MIT license. Check and compile Osiris with OsiCheck and extracted game sources, or use the optional native Toolkit backend.

## Features

- Osiris goal, definition and log highlighting, plus snippets.
- BG3 completion, parameter hints, hover, go to definition, references and document symbols.
- API signatures and enum members read from your project's header or cached from the game files after an OsiCheck run.
- Dependency procedures indexed from a prepared Toolkit `goals.raw` snapshot when available.
- Live syntax diagnostics, including `IFF` global rules and BG3 enum literals such as `ARMOURSET.Normal`.
- A Story Goals tree following parent relationships between mod-owned goals.
- **BG3 Osiris: Check Story (OsiCheck)** and **BG3 Osiris: Build Story** commands, with source diagnostics in Problems.
- A build task available with **Ctrl+Shift+B**, plus a Check Story task.
- Real `story.div.osi` output from either OsiCheck or the installed Toolkit's native compiler.
- **Build and Install Story** installs only successful, unchanged builds with backups. Ordinary **Build Story** keeps outputs in staging.
- **Update Game Content (Jinx Tools)** starts our shared authoring update and opens its progress page. Native resource updates use the running Toolkit through Jinx Tools; the Story Editor does not need to be opened.

## Requirements

Editing works in desktop VS Code 1.85 or newer. Checks and builds require Windows x64 and Python 3.10+.

The **OsiCheck backend** requires an external copy of the supplied OsiCheck distribution, .NET 8 or newer, the BG3 game files, and extracted dependency story sources. Those sources must include `story_header.div` and the dependency modules' raw goals under `Data/Mods/<module>/Story/RawFiles`. It does not load Toolkit DLLs or require Prepare Project, generated headers for your own project, or an existing compiled mod story. The supplied compiler binaries are not redistributed in the VSIX.

**Retail game packages alone are insufficient.** This backend uses the extracted sources already present in a modding setup; it does not reconstruct them from compiled stories. A missing-input error explains this requirement before an output can be produced. The Toolkit can provide these inputs, but it does not need to run or remain installed for subsequent OsiCheck checks/builds if the extracted inputs are retained. Obtaining a complete, compatible source set directly from a retail installation is not implemented.

The **Toolkit backend** additionally requires .NET 10, an installed BG3 Toolkit, and a prepared baseline from a successful Toolkit build.

The compiler host currently supports the inspected `Osiris.dll` with SHA-256:

```text
340d688aca31cc399c4639529a3381f1a7e57e489d7501dbc337eff90a91e6fc
```

A different DLL is rejected. Supporting another Toolkit build requires checking the compiler ABI and serializer before adding its identity. The game DLL is read from your installation and is never included in this extension.

## OsiCheck: check and build without the Toolkit

1. Install the `.vsix` with **Extensions: Install from VSIX**. Disable the original Divinity extension for this workspace if installed; it shares the language IDs.
2. Keep the complete supplied OsiCheck folder wherever you store modding tools. Set **BG3 Osiris: OsiCheck Path** to that folder or its `bin` folder.
3. Open your module folder or its `Story`, `RawFiles` or `Goals` subfolder. Set **Game Data Path** if automatic detection cannot locate BG3's `Data` folder.
4. Run **BG3 Osiris: Check Story (OsiCheck)**. API completion and parameter hints are refreshed from the selected game header after the run.
5. Run **BG3 Osiris: Build Story**, or **Ctrl+Shift+B**, to produce a staged `story.div.osi`.
6. Run **BG3 Osiris: Open Last Build Output** to locate the compiled file and report. Check-only runs do not replace the last build or produce an `.osi`.

**Compiler Backend** defaults to `auto`: configuring OsiCheck Path selects OsiCheck; otherwise the Toolkit is used. Choose `osicheck` or `toolkit` explicitly to keep one backend selected. Check Story always uses OsiCheck, and Prepare Project always uses the Toolkit.

OsiCheck compilation is experimental until its output has been validated in gameplay. It has passed isolated builds with only the new project's goal sources plus extracted game dependencies, binary readback, enum and global IFF checks, and invalid-source failure checks. Keep the native backend available when comparing compiler behavior.

**Dependency Mods** lists module folder names in load order; the project is loaded last. Its default includes the standard game, Honour and HonourX modules. Add custom dependencies here when required by your project.

The four exact vanilla unused-database exemptions supplied with OsiCheck are visible in output and the JSON report. They are applied before compilation so the compiler can generate a story, and are disabled for a database mentioned by the project's own sources. Other unused-database errors still fail the build. Set **OsiCheck Known Vanilla Issues** to an empty list to disable the exemptions.

OsiCheck reads installed package files and copied source inputs in an isolated worker. It snapshots the project's goals, detects changes during compilation, rejects activation cycles, and verifies the saved story's rule count, global IFF links and enum table count before exposing the result. It does not silently substitute `IF` for `IFF`. It preserves the dependency sources directly; it does not regenerate them through a decompiler.

## Optional native Toolkit build

1. Install the `.vsix` with **Extensions: Install from VSIX**. Disable the original Divinity extension for this workspace if installed; both use its language IDs for compatibility.
2. Open your module folder (`Data/Mods/YourModule_UUID`) or its `Story`, `RawFiles` or `Goals` subfolder. The module is detected automatically. Opening a goal file directly also supplies its module to the language service and build commands.
3. Set **BG3 Osiris: Toolkit Path** to the directory containing the Toolkit's `Osiris.dll`.
4. In the Toolkit, generate definitions and complete one successful Story build for this module.
5. Run **BG3 Osiris: Prepare Project from Toolkit Build**. This captures the dependency story, header, definitions and orphan-query settings into local extension storage.
6. Edit your goals, then run **BG3 Osiris: Build Story**, or use **Ctrl+Shift+B**.
7. Run **BG3 Osiris: Open Last Build Output** to find `story.div.osi`, its input files, compiler log and JSON report.

Builds are staged in VS Code's extension storage. They do **not** install a story into the game, reload an editor session, or package a mod. Install the output through your normal mod workflow after reviewing the successful build. A failed build produces no usable `.osi`.

Leave **BG3 Osiris: Project Path** empty for automatic discovery. An explicit value can point to the module or a folder inside it and overrides discovery; clear any stale value when switching modules. Build commands ask which module to use when several are available. The language service shares API symbols between modules in a multi-module workspace; use separate windows for modules with incompatible headers or conflicting custom symbols.

Goal `.txt` files need the complete Osiris file structure. Type `goal` and choose the goal snippet to insert the section headers, then put `IF`, `PROC` and `QRY` rules inside `KBSECTION`. Bare rules receive one explanatory diagnostic instead of a cascade of unexpected-token errors.

## What the native compiler does

The backend preserves dependency goal blocks, order and activation relationships from a successful Toolkit build. It merges current mod-owned goal files, validates parent references and cycles, and runs the native compiler in a separate worker process. This provides native symbol resolution, type inference and BG3 enum support. Diagnostics are mapped to edited goal files where the compiler's source location is available.

Baseline hashes are checked before every build. Edits made before preparation are detected rather than silently replaced with old source. Compiler failures and process crashes leave the module's working story untouched.

After a Toolkit/game update, dependency changes, or changes requiring new generated object definitions, generate definitions and build in the Toolkit again, then run Prepare Project again. The previous baseline is archived beside the new one. A changed compiler still requires ABI verification before it is supported. This first version does not regenerate engine definitions itself.

Preparation captures the last successful Toolkit build even when an open goal is empty or unfinished. Such drafts are marked for recompilation and must be completed before Build Story can succeed. Failed preparation leaves the previous completed baseline usable. Build errors identify any source file missing its goal sections.

The inspected native compiler retains `IFF` rules with a global goal reference of zero. An isolated binary regression check verifies that changing a probe from `IF` to `IFF` changes only that reference; it does not remove the rule graph. This linkage also occurs in the shipped game story. LSLib's per-goal decompiler omits rules without an owning goal, so decompiled goal text alone cannot establish whether `IFF` rules survived. This backend preserves generated source directly and does not rebuild dependencies from decompiled goals. Gameplay execution of the isolated probe has not been tested.

The native compiler may refuse output even when it reports only warnings, such as an unchecked database. Those builds are reported as failed; fix the warnings before using the output.

Live diagnostics check syntax. Check Story and compiler builds check types and dependency resolution. Runtime gameplay behavior still needs testing in the game or Toolkit.

## Command-line build

```powershell
python tools/osicheck_backend.py check --project "D:\Mods\MyMod_UUID" --osicheck "D:\Tools\OsiCheck" --game-data "D:\BG3\Data" --state-dir "D:\Builds\MyMod"
python tools/osicheck_backend.py build --project "D:\Mods\MyMod_UUID" --osicheck "D:\Tools\OsiCheck" --game-data "D:\BG3\Data" --state-dir "D:\Builds\MyMod"
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
npm run build:osicheck
npm run package
```

Building both workers from source requires the .NET 10 SDK and .NET 8 reference pack. OsiCheck's binaries are resolved at runtime from the configured installation, and are not needed to build our worker. The packaged extension needs only the appropriate runtime.

Run standalone integration tests against the supplied OsiCheck and installed game:

```powershell
python tools/test_osicheck_backend.py --osicheck "D:\Tools\OsiCheck" --game-data "D:\BG3\Data"
```

These tests create a source-only project with no project header, `goals.raw`, prepared baseline or existing `.osi`, using the extracted game dependencies. They check enum and IFF preservation, check-only behavior, source diagnostic locations, ordinary unused-database errors, malformed goals, activation cycles and unchanged installed stories. A separate test disables all loose dependency inputs and verifies that retail packages alone fail with actionable guidance rather than producing an incomplete story.

Run native integration tests against a module with a successful Toolkit build:

```powershell
python tools/test_bg3_osiris.py --project "D:\BG3\Data\Mods\MyMod_UUID" --toolkit "D:\BG3 Toolkit"
```

Tests copy module inputs into temporary local storage. They compare the output with the Toolkit binary excluding its timestamp, compile a new BG3 enum goal, reject an invalid procedure and check its diagnostic location, and verify edits made before preparation are retained. A separate native probe checks that `IFF` preserves the binary graph and changes its goal reference to zero. The module's existing `Story/story.div` must be from a successful Toolkit build. Test stories are never installed.

The Marketplace publisher is `jinx`. This BG3 fork is maintained at [JinxRunes/bg3-osiris-vscode](https://github.com/JinxRunes/bg3-osiris-vscode); report extension issues there. The separately installed OsiCheck distribution and local build storage are excluded from source control.

## Attribution and scope

The original extension's license, grammars, snippets and syntax parser are retained. The parser used by the new service is isolated in `src/bg3/parser`; upstream DOS2 sources remain for reference. The new service and commands do not run the original DOS2 tool downloader, debugger installer or reload commands.

This BG3 version focuses on Osiris editing, checking and compilation. The old API Explorer webview, semantic rename, DOS2 debugger and automatic runtime reload are not advertised as BG3 features. API links open the official BG3 modding documentation.
