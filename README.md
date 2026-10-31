# Prompt conditioned sound creation claim audit

An offline static checker for documented generative model track synthesis.
Requires Python 3.9 or later and has no runtime dependencies.

```sh
pip install audio-generation-claim-audit
audio-generation-claim-audit . --json
python3 -m audio_generation_claim_audit . --verbose
```

The checker reads root README.md and Markdown files beneath any docs path
component. Fenced examples are omitted; inline code counts. It joins paragraph
lines, expands negative contractions, and normalizes hyphens and whitespace.
Exact templates use word boundaries, with longer matches first and negative
spans removed before positive matching.

Evidence includes imported AudioLDM, AudioLDM2 and StableAudio pipeline
construction or loading, MusicGen model construction or loading, Transformers
prompt-to-sound task calls, and hosted music.generate calls. Aliases are resolved
within a module, with local definitions taking precedence. Speech synthesis,
transcription, playback, capture, writing existing samples, analysis, and clip
classification do not establish this capability.

Rules:

```text
documented-audio-generation-claim-false: HIGH without production evidence;
MEDIUM when evidence appears only in tests.
documented-no-audio-generation-claim-false: HIGH when production evidence
contradicts a negative statement.
```

No matching statement yields PASS. JSON includes verdict, findings (rule,
severity, message), and files_scanned. Human output includes each finding;
--verbose adds the scanned count. A finding produces a FAIL verdict even when
its severity is below the selected exit threshold.

Use repeatable --ignore glob patterns against relative POSIX paths.
--fail-on HIGH is the default; --fail-on MEDIUM also fails on test-only evidence.
Exit codes are 0 for no findings at the selected threshold, 2 for findings at
that threshold, and 1 for invalid arguments or unreadable input. --version
prints 0.1.0.

Python files are parsed without execution. Symlinks are skipped. Files beneath
fixtures, docs, and examples are excluded from evidence. Test paths and names
are tracked separately. Invalid syntax supplies no evidence. This is a heuristic:
construction does not prove successful inference, model quality, network access,
or working credentials. Dynamic imports, cross-module data flow and runtime
rebinding are outside scope; hosted calls accept any receiver name.

Run the bundled suite with `python3 -m unittest discover` and build isolated
artifacts with `python3 -m build`.
