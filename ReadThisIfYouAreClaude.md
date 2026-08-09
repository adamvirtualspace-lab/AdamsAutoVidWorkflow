# Read This If You Are Claude

You've been dropped into a project that already has a working pipeline. Don't
redesign it, don't skip steps, don't guess at formats — read the example file
for whatever step you're on and match it. This doc walks the six stages in
order and tells you, for each one, whether to run a `.bat` or do the work
yourself.

**The one rule that matters most:** every step that says "AskAI" has a `.bat`
that would normally shell out to DeepSeek. **Don't run that `.bat`.** Do the
reading and writing yourself, right here in the conversation, using your own
judgment instead of a scripted API call. You have the context of this chat and
can actually watch/reason about the content; a scripted DeepSeek call can't.
Everything else — compiling, transcribing, converting, exporting — run the
`.bat` as-is. Those are mechanical and there's no reason to redo them by hand.

Work from the project root (e.g. `E:\AdamsRoadTrips\SnowRunnerPart02`, a copy
of this template). All paths below are relative to that root.

---

## Step 1 — `01_RAW`

Put the raw gameplay recording(s) in here. All three steps are mechanical,
run them in order:

```
01_RAW\A_RunThisToCompileMP4.bat
01_RAW\B_RunThisToLevelAudio.bat
01_RAW\C_RunThisToReplaceAudio.bat
```

A compiles multiple files into one `COMPILED_VIDEO.mp4` (or just re-encodes a
single one to a consistent fps).

B evens out the speaking volume (Audacity-style compressor + loudness
normalize) and writes it to a standalone file,
`COMPILED_VIDEO.leveled_audio.m4a`. **`COMPILED_VIDEO.mp4` is not touched by
this step** — re-run B as many times as you want (e.g. after tweaking the
filter in `level_audio.py`) with no risk of compounding the effect, since it
always reads from the original recording, never from its own output.

C puts that leveled audio into `COMPILED_VIDEO.mp4` — video stream copied
untouched, audio track swapped in. It keeps the untouched original as
`COMPILED_VIDEO.original.mp4` the first time it runs, so
`python replace_audio.py --revert` always gets you back to raw audio.

---

## Step 2 — `02_RawSubtitles`

Run:

```
02_RawSubtitles\RunThisToGenerateSubtitle.bat
```

This transcribes `01_RAW`'s video with whisper and writes a raw SRT. Mechanical.
Run it. Note the case-sensitivity warning it prints about `.mp3` — it's
checking file extensions literally.

---

## Step 3 — `03_EditPlanToOtio` — **AskAI: do this yourself**

**Do NOT run** `A_RunThisToMakeEditPlan_WithDeepSeek.bat` or
`A_RunThisToMakeEditPlan_WithLocalAI.bat`.

Instead:

1. Read the `.srt` in `02_RawSubtitles\` (the filename varies per project —
   check what's actually in there) and understand the actual content — what
   happened, what's funny, what's dead air.
2. Read `03_EditPlanToOtio\editplan_example.md` for the exact format: header,
   `## Editing Philosophy`, `## Segment Cut List` prose sections, and the
   `## Summary: Cut List (by timecode)` table are all required — the table is
   what actually gets parsed, but the prose above it is where you think out
   loud and is worth keeping for a human reader.
3. Decide what to keep and cut. Keep the fun/interesting stuff, cut long
   silences, repetitive menu navigation, dead driving with no commentary.
   There's no fixed target length — let the content decide.
4. Write your plan to `03_EditPlanToOtio\editplan.md`, following the example's
   structure. Use the real recording's filename and duration in the header, not
   the example's.

Then convert it — this part IS mechanical, run it:

```
03_EditPlanToOtio\B_ReConvert_EditPlan_To_OTIO.bat
```

Open the resulting `editplan.otio` in Resolve/Kdenlive if you want a human to
sanity-check the cuts before continuing. If they re-export it, it overwrites
`editplan.otio` directly — that's fine, later stages just read whatever's
there.

---

## Step 4 — `04_FinalSubtitle`

After the edit plan's `.otio` is finalized (by hand-checking or not), run the
three `.bat`s in order — all mechanical:

```
04_FinalSubtitle\A_RenderAudioForSRT.bat
04_FinalSubtitle\B_GenerateFinalSubtitle.bat
04_FinalSubtitle\C_FinalSubtitleToOtio.bat
```

- A renders cut audio from `03_EditPlanToOtio\editplan.otio`.
- B transcribes that audio to `04_FinalSubtitle.srt` — this is the **final
  cut's** subtitle, in the edited video's own timeline (starts at 00:00:00).
- C turns that SRT into `FinalSubtitle.otio` (one title clip per cue).

Don't touch the `--start-tc` flag baked into C's command — it's there because
this SRT is zero-based, not because of the intro/highlights stage. Leave it.

---

## Step 5 — `05_Memes` — **AskAI: do this yourself**

**Do NOT run** `A_AskAIToMake_MemeEditPlan.bat`.

Instead:

1. Read `04_FinalSubtitle\04_FinalSubtitle.srt` (the FINAL cut's subtitle, not
   the raw one from step 2).
2. Read `05_Memes\.scripts\memeeditplan_example.md` for the table format:
   `# | SRT Time | Subtitle Context | Meme Image | Meme Name | Duration`.
   The **SRT Time column is a range** (`00:00:00 - 00:00:06`) but only the
   *start* is used to position the clip — the end is just context, the
   Duration column controls how long it's shown.
3. For each funny/interesting moment, pick a meme, invent a lowercase
   underscore filename ending `.jpg` (e.g. `this_is_fine.jpg`), and a 3-6s
   duration (shorter for quick reactions).
4. Fill the header exactly — this part is NOT decorative, get it right:
   - `**Video:** ... (Xm Ys)` **must be the real duration of the final cut**,
     not copied from the example. It sets the OTIO timeline length; too short
     and memes past that point get silently cut off.
   - The meme folder line under `## Notes` must read
     `- All meme images located in \`<absolute path>\05_Memes\memes\`` — that
     exact folder name. (An earlier version of this pipeline wrote `.memes\`
     here, which broke things; don't reintroduce that.)
5. Write it to `05_Memes\memeeditplan.md`.
6. **Download the meme images yourself** using whatever image search / fetch
   tools you have — save them into `05_Memes\memes\` under the exact filenames
   you used in the plan. (`B_DownloadThePlannedMemes.bat` does this via DDGS if
   you'd rather run it, but doing it yourself lets you actually look at the
   image before saving it, which is worth it — a mismatched or dead-link meme
   is a worse failure mode than a slow download.) Verify each image actually
   opened and shows a real picture, not a placeholder/broken-image icon.

Then convert — mechanical, run it:

```
05_Memes\C_ConvertMemeEditPlanToOTIO.bat
```

---

## Step 6 — `06_Final`

### 6A — cold open — **AskAI: do this yourself**

**Do NOT run** `A_AskAIToPickHighlights.bat`.

This step is optional — skip it entirely and there's simply no cold open, the
final video starts straight at the edit.

If you do want one:

1. Read `04_FinalSubtitle\04_FinalSubtitle.srt` again (final-cut time).
2. Read `06_Final\.scripts\highlights_example.md` for the format.
3. Pick exactly 3 moments that land without setup — funny or dramatic on
   their own. 5-10s each, the three together under ~30s. Order them for
   punch, strongest first, not chronological.
4. Write `06_Final\highlights.md`. Timestamps are **final-cut time**, the same
   clock the SRT uses — and the Cut Time range *is* the clip, start to end.

### 6B onward — mechanical, run in order

```
06_Final\B_CombineFinalTimelines.bat
06_Final\C_ConvertFinalTimelinesToFCPXML.bat
06_Final\D_ExportToCapCut.bat
```

- B accumulates `editplan.otio` + `FinalSubtitle.otio` + `memeeditplan.otio`
  (+ the cold open, if `highlights.md` exists) into
  `FinalTimelineNoCap.otio` / `FinalTimelineWithCap.otio`. It resamples
  everything onto the edit's frame rate automatically — stages don't need to
  share an fps.
- C writes `.fcpxml` next to each `.otio`, for Resolve.
- D exports `FinalTimelineNoCap.otio` (deliberately the no-captions one — ~3000
  one-word caption clips make an unusable CapCut timeline; CapCut has its own
  caption tools) into a CapCut draft project.

---

## Quick reference: what's AskAI vs mechanical

| Step | AskAI (you do it) | Mechanical (`.bat`) |
|---|---|---|
| 1 RAW | — | compile → level audio → replace audio |
| 2 RawSubtitles | — | transcribe |
| 3 EditPlanToOtio | **write editplan.md** | convert to otio |
| 4 FinalSubtitle | — | render audio → transcribe → convert |
| 5 Memes | **write memeeditplan.md + fetch images** | convert to otio |
| 6A Final (highlights) | **write highlights.md** (optional) | — |
| 6B-D Final | — | combine → fcpxml → capcut |

If you're unsure whether something counts as "AskAI," the tell is in the
filename: anything starting `A_AskAI...` or `A_RunThisToMakeEditPlan...` is a
step you do yourself instead of running. Everything else, run as written.
