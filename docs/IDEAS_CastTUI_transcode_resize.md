# Idea: transcode resize / quality options

The live ffmpeg transcode (`TranscodeServer`, enabled by `config.transcode`)
already accepts a `scale` argument — `ffmpeg_transcode_cmd(path, scale=720)`
adds `-vf scale=-2:720` to cap the output height while preserving aspect. It is
wired through `CastService.play_file(path, transcode=True, scale=...)` but not
yet exposed in the UI or config.

To finish the resize option later:

- Add a `transcode_scale` preference to `Config` (e.g. 0/None = source height,
  720, 480). Thread it into `app._serve_file` → `play_file(..., scale=...)`.
- Surface it in the Cast view (a small selector) or Settings when that view
  exists. A lower height means less CPU and bandwidth, useful on weaker hosts
  or flaky Wi-Fi; the trade-off is picture quality.
- Consider a matching `-crf` / `-preset` knob for quality vs CPU, and `-b:a`
  for audio. Keep `veryfast` as the default preset (real-time 1080p on a
  modern desktop).

Non-goals stay the same: this is on-the-fly casting convenience, not a
transcoding/library tool (SCOPE_CastTUI.md §2).
