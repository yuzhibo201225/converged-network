# Development/native release verification reproduction

ARS-Codex assistant execution support,2026-10-13. No full emulator/network
execution or outside-review claim. Source pin/split and preceding protocols
define what is, and is not, inspected.

```powershell
python -m converged_sim.cellreplay_code_source --out results/cellreplay_code_source_v21
python -m converged_sim.cellreplay_development_screen --source results/cellreplay_source_v20 --split results/cellreplay_split_v20/split.json --code-source results/cellreplay_code_source_v21 --out results/cellreplay_development_v21
python -m converged_sim.cellreplay_release_probe --source results/cellreplay_source_v20 --split results/cellreplay_split_v20/split.json --development results/cellreplay_development_v21 --code-source results/cellreplay_code_source_v21 --out results/cellreplay_release_probe_v22
python -m converged_sim.audit_release_probe --input results/cellreplay_release_probe_v22 --out results/cellreplay_release_audit_v22
python -m converged_sim.native_release_check --source results/cellreplay_source_v20 --split results/cellreplay_split_v20/split.json --development results/cellreplay_development_v21 --code-source results/cellreplay_code_source_v21 --planned results/cellreplay_release_probe_v22 --out results/native_release_v23b
python -m unittest discover -s tests -q
```

Use the project's Python runtime and existing C:/msys64/mingw64/bin/g++.exe.
Compiler environment prefix recorded in the native freeze; build/runtime logs
retained. No install or persistent environment mutation. All outputs refuse
existing target directories; reproductions use new names, never erase old ones.
The first failed native directory remains, with its frozen original runner;
the V23 environment-only repair is documented separately.

The C++ fixture contains exact selected upstream methods plus standalone I/O
instrumentation; GPL notices retained and source-method containment verified
byte-for-byte. It does not contain the original operating-system/network shell
or heavy queue. Excluded domain: wraparound, >1400B content, signed-underflow
offset cases and unverified data. No claim of equivalence outside tested inputs.

Raw source archive, numeric development screen, planned gzip CSV, native CSV,
compiled fixture and all hashes remain local under ignored results/. Only
receipts/protocols/authored verification scripts enter this private local Git
checkout. No private or reserved data uploaded, no public PR/issue/repository.
