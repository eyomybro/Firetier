# Firetier debugging milestone

**Decision: suitable for a limited Windows 11 pilot of local profile management. General release remains unqualified.** A damaged backup now leaves the destination intact. A copied profile can be renamed without changing its original. The minimum-width editor is usable, and the extracted app saved, restarted, exported and reset a profile with its bundled runtime.

## Scope and build

Audited the active Firetier project in the supplied Windows workspace: both application modules, every Tk tab, the Windows launcher, README and existing tests. Firetier uses a JSON filesystem store, Tkinter and a procedural preview. The separate Facet projects have a different implementation. Database persistence below means Firetier's actual on-disk profiles and preferences. There is no database server, standalone game picker, image-asset library or dashboard page in this build. Rivals selection was exercised through its named preset.

Windows 11 AMD64 build 26100, Python 3.14.6, Tk 8.6. The tested archive is `dist/Firetier-Windows.zip` (12,217,819 bytes). SHA-256: `e3bdea8906854eb70e64465bb95b28b43c70e0132c168d4b3247d2db657774e4`. Extract the entire archive, then open **Firetier.bat**. The package smoke test used a path containing spaces and removed system Python from PATH.

## Findings and evidence

| Area | Highest-impact observation | Verification |
|---|---|---|
| Backup and filesystem transactions | A bad payload was installed before integrity failure was reported. Partial manifests could interrupt recovery. | Damaged payload refused through the actual Backups tab, healthy target byte-identical. Good backups restore content and absence. [Failure screenshot](evidence/restore-refused.png) |
| Profiles and import | Copied-file ID mismatch could redirect writes. Invalid types could break library loading. An engine caller could clear settings by replacing from a stored-only import. | Identity, schema, isolation, reimport, archive classification and apply tests. Original damaged files retained. |
| Preferences and shutdown | Bad settings could crash startup. A failed save could be silent. Cancelling a follow-up dialog could lose the dirty indicator. | Startup recovered the prior configuration, preserved damaged bytes and reported write failure. Dirty-state regression and two-process restart passed. |
| UI and preview | The flag-name entry collapsed at minimum width. Identical previews were regenerated. Archived assets displayed a default scene as their result. | Measured widget width, real captures, render-count regression, archive-to-preset transition and repeated switches. [Before](evidence/before-flags.png) · [After](evidence/after-flags.png) · [Difference](evidence/flags-difference.png) |
| Diagnostics | Slow system queries ran in the Tk event loop. Failures looked like an empty process list. | A delayed worker allowed 46 UI ticks in 450 ms. The Windows query failure was visible in the fixture run. Select a check for its full result. [Diagnostics](evidence/diagnostics.png) |
| Concurrency and recovery | Individual atomic writes left the surrounding backup/apply cycle exposed to other writers. | Two-process contention, owner termination, simulated external edit during backup, worker process death during flush, and injected memory failure. |
| Windows distribution | The original BAT launcher depended on an installed Python and had no Firetier portable build. | Archive CRC checked. Bundled launcher opened a real window five times and closed cleanly five times. A second packaged workflow checked saved contents following restart. [Packaged window](evidence/packaged-window.png) |

The [regression history](REGRESSION_HISTORY.md) lists symptoms, root causes, individual corrections and named tests. The first harness run used an unwritable sandbox temp directory. Repeating with a writable directory gave the original baseline of **30/30**. Before correction, the initial 11-case engine fault suite reported eight failing assertions and six errors, including subtests. The first six desktop fault cases reported five failures and one error. The final suite passed **54/54 in 11.030 seconds**, including 24 added tests. Desktop workflow, stress and package programs ran separately. [Full unit and integration output](evidence/test-results.txt)

## Desktop workflow actually exercised

| Stage | Observed result |
|---|---|
| Launch, navigate and select Rivals | Opened the actual Tk application, selected both Rivals presets through the tree, and read the Status tab. |
| Create and import | Pressed New, imported a flat FastFlag JSON through the Import control, and confirmed its recorded source format. |
| Edit rules, preview and save | Changed the sky rule in each direction. The preview caption changed for each edit, and the selected scene displayed the low-texture preset. Saved through the button. [Actual preview](evidence/preview.png) |
| Apply and restart | Replace wrote the 12 effective flags to a fixture installation. Closed normally and started a fresh process. Active profile ID, saved rule value and apply mode persisted. |
| Export and recover | Exported rule data matched the saved profile. Restored the target to its exact original bytes, including its newline. Reset application preferences and deleted a profile to trash. |
| Packaged workflow | The bundled Python opened Firetier, created and saved an editable rule, rendered the grey-sky preview, restarted, verified the selected profile, exported it and restored default preferences. |

The harness invoked real Tk widgets and supplied deterministic answers to native confirmation, name and filename dialogs. The separate package smoke test launched the actual BAT and sent a normal Windows window-close message. It measured 2.092, 1.006, 0.838, 0.840 and 0.843 seconds to an observable window. The local workflow log contained three successful checks, two warnings and zero diagnostic failures. One warning was the deliberately invalid fixture flag and the other was the unavailable Windows process query. [Workflow log](evidence/workflow-log.txt) · [Package results](evidence/package-test.json)

## Stress and memory

| Scenario | Measured outcome |
|---|---|
| 30 imports with 10,000 asset references each | 4.408 s including saving and reloading the collection. All 30 IDs distinct and the reference count persisted. |
| Large or invalid input | An 18 MiB valid, unknown-format JSON was classified in 73 ms. A file one byte above 20 MiB was refused. An 8192 × 8192 PNG was rejected by the JSON importer. Firetier has no image-decoding import path. |
| Actual process memory limit | With a Windows job limit of 25,579,520 bytes, a 10 MiB import returned an explicit insufficient-memory result. A separate write fault test verified the previous bytes and temp-file cleanup. |
| Preview switching | Nine warm switches across the same three presets measured a 766.5 ms median in the original application and 55.6 ms after correction. In a longer corrected run of 240 switches the median was 51.83 ms, p95 64.03 ms and maximum 143.62 ms. |
| Resource retention | Working set was 81.77 MiB initially and 81.98 MiB at switches 60, 120, 180 and 240. Tk image count remained eight. The run covers this workload and duration. |
| Interruptions | A child exited during flush before replacement. The prior target remained byte-identical. A competing app operation was refused while its peer held the mutex, then succeeded after the peer was killed. |

The asset-import timing exercises the storage engine. The switch timing exercises the actual visible Preview tab with a small preset collection. Those timings describe different workloads. [Raw performance measurements](evidence/performance.json)

## Historical compatibility

The latest public release link resolved to v2.4.1 when checked. The reports below have different evidence and platforms. None establishes today's behavior of a live Rivals session. [Fleasion public release](https://github.com/fleasion/Fleasion/releases/tag/v2.4.1)

| Report | What the source establishes | Applicability to this Firetier build |
|---|---|---|
| Critical settings and 529, #88 and #93 | Windows users reported failed joins with Fleasion's proxy enabled. In #88, disabling profiles did not resolve the symptom. #93 described a different config-dependent result in Rivals. These are observations, with no universal cause demonstrated. | Firetier has no proxy or join workflow. No live 529 reproduction was attempted. [#88](https://github.com/fleasion/Fleasion/issues/88) · [#93](https://github.com/fleasion/Fleasion/issues/93) |
| ClientSettings, #115 | A contributor attributed the v2.4.1 regression to a forced certificate-related flag, then reported that the initially proposed partial fix failed on Windows. A full revert was proposed. | Firetier's historical fixture classified the reported flag as ignored, and applying that fixture in Merge left the target intact. Firetier can preserve pre-existing unknown flags in Merge. [#115](https://github.com/fleasion/Fleasion/issues/115) · [#119](https://github.com/fleasion/Fleasion/pull/119) |
| Missing replacements, asset-delivery v3, #124 | The reporter documented a v3-versus-v1 mismatch using Sober on Linux, with captured request counts. This evidence is specific to that client and Fleasion implementation. | Firetier has no delivery handler. The local asset-reference fixture was archived, and both apply modes preserved the target. [#124](https://github.com/fleasion/Fleasion/issues/124) |
| Profile application, #143 | A Windows user reported working flags alongside failed replacements. The issue was closed as a duplicate. The reporter disputed that diagnosis. | Verified local settings writes, readback, and archive-only behavior. Live asset application is outside the implementation. [#143](https://github.com/fleasion/Fleasion/issues/143) |
| Local FastFlag compatibility | Roblox documents an allowlist for local client configuration and reserves the ability to change it. The 18 names in Firetier matched the list consulted. | File readback and a rendered preview cannot establish an in-game effect. [Roblox announcement](https://devforum.roblox.com/t/allowlist-for-local-client-configuration-via-fast-flags/3966569) |

## Open issues and release limits

- **Environment coverage.** One Windows 11 x64 host. Clean Windows 10, ARM64, multi-monitor DPI changes, other language packs, and extended soak testing remain open. No signing or SmartScreen reputation assessment was performed.
- **Recovery boundaries.** A sudden process kill can lose unsaved in-memory edits. Staging files and incomplete backup directories can remain. Interrupted backups are reported for inspection. Real power loss and full-volume exhaustion were not exercised.
- **Concurrent external programs.** Firetier serializes its own operations and detects a change during backup. Another program can still modify the file after the last observation or after verified readback.
- **Scale.** Cold rendering, large profile collections, backup enumeration and imports still perform synchronous work in parts of the GUI. There is no retention limit for backup history. The 30-import storage test does not establish UI latency at that size.
- **Trust and validation.** Backups use SHA-256 for accidental corruption and local filesystem permissions for trust. A user able to modify both the manifest and payload can alter both. Broad permission-denial, filesystem reparse-point and hostile local-user testing remain open. The asset-ID heuristic can classify unrelated numeric IDs as archived references.
- **Live behavior and missing features.** No Roblox account, live session, production settings or cached game assets were used. The supported workflow draws an offline comparison and edits local settings. Asset image previews, live texture replacement and game-specific visual effects remain unverified or unavailable as indicated above.

See the [debugging guide](DEBUGGING_GUIDE.md) for commands, diagnostic paths and recovery procedures, and [engineering lessons](ENGINEERING_LESSONS.md) for the component and transaction diagram.

