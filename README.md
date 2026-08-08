# AdamsAutoVidWorkflow
### Welcome! This is Just My personal workflow to automate my gameplay video creation longform and shortform
## And so far, the Plans are here :

## Running everything at once
`StartEverythingUsingDeepseek.bat` runs steps 1-6 in order, unattended, using
DeepSeek for the three AskAI steps (edit plan, meme plan, highlights). Stops
and tells you which step failed if anything goes wrong; nothing after that
point runs. If you'd rather have an AI assistant sitting in the chat do the
three AskAI steps itself instead of DeepSeek, see `ReadThisIfYouAreClaude.md`
and run the individual step `.bat`s by hand.

Every step `.bat` still runs fine on its own, double-clicked or from a
terminal, with its normal pause at the end — the orchestrator just sets
`NONINTERACTIVE=1` to skip those while it's driving.

# Step 0. cd Into this directory 
# Step 1. [01_Raw] :
First Put the Raw Video Files into "01_RAW" Folder, then compile (if multiple sequencing video, into one video)

# Step 2. [02_RawSubtitles] :
From that video (or compiled video). use tools neccessary to extract subtitle, and put it into 02_RawSubtitles

# Step 3. [03_EditPlanToOtio] :
Otio is a "Open Timeline IO" format, a Format about video&audio timeline.
Use an AI and use prompt something like this : 

[USE PLAN MODE]
Can you edit a video? by just reading a subtitle file, understand the context, and then make and write edits in .otio format ? if can, then please read this subtitle and understand the context first, and make editplan.md of what should we keep and what should we cut. i prefer to include all the fun and interesting stuffs while just cut away the boring or silence moments. In current directory can check that theres `\01_RAW\SnowRunnerPart2.mp4` that i have generate the subtitle using voice recognition and the subtitle is `\02_RawSubtitles\SR02_Subtitle_KdenliveExport01.srt` 

Then this :

[USE BUILD MODE] 
Ok, now write the editplan to EditplanToOtio\editplan.md and please write it according to editplan_example.md

## Step 3A [03_EditPlanToOtio] :
Just run `B_ReConvert_EditPlan_To_OTIO.bat` — it cd's to its own folder and
converts `editplan.md` into `editplan.otio` for you.

To run it by hand instead, from inside `03_EditPlanToOtio`:
`python .scripts_and_examples\EditPlanToOTIO.py editplan.md`

# Step 4 [04_FinalSubtitle] :
Open `03_EditPlanToOtio\editplan.otio` in Davinci or Kdenlive, check the cuts,
and export it back over the same file. Then run the three .bats in order:

- `A_RenderAudioForSRT.bat` — reads `03_EditPlanToOtio\editplan.otio`, turns it
  into an ffmpeg concat list, and renders the cut audio to `04_FinalAudio.MP3`
- `B_GenerateFinalSubtitle.bat` — transcribes that MP3 to `04_FinalSubtitle.srt`
- `C_FinalSubtitleToOtio.bat` — turns the SRT into `FinalSubtitle.otio`
  (a title clip per cue, ready to drop on a caption track)

Note: the SRT that comes out of B is zero-based (starts at 00:00:00), which is
why C passes `--start-tc 00:00:00:00`. If you ever feed it an SRT exported from
a Resolve timeline instead, drop that flag — those carry a 1-hour offset.

# Step 5 [05_Memes] :
Use an AI and use prompt something like this : 

hi, from current directory, inside it can you see `\04_FinalSubtitle\04_FinalSubtitle.srt` ? please understand the context from the subtitle, and please decide what memes should be appropriate on each funny or interesting moments according to the srt. and write the editplan like the format of `\05_Memes\.scripts\memeeditplan_example.md` also download all the necessary memes jpegs or png and put it all in this folder ( `\05_Memes\memes\`) then write the edit plan in current directory, as `\05_Memes\memeeditplan.md` for grabbing the memes of the internet, can just use any tools available at your disposal. you are on windows btw, so don't use bash. use shell commands. also maybe use searxng for search if you have trouble. if you have vision, please check at the images you downloaded, make sure its valid as an image. not "that this images is no longer available or something.

Or skip the chat and just run the .bats in order:

- `A_AskAIToMake_MemeEditPlan.bat` — sends `04_FinalSubtitle.srt` to DeepSeek and
  writes `memeeditplan.md`. It fills the header (project name, SRT name, real
  duration) and the meme folder itself, so don't let the AI copy those from the
  example file.
- `B_DownloadThePlannedMemes.bat` — reads the plan and downloads every image into
  `05_Memes\memes\`. Safe to re-run; it skips what's already there, so it only
  chases the ones that failed.

## Step 5A [05_Memes] - Creating the meme timelines:
Run `C_ConvertMemeEditPlanToOTIO.bat`. It reads `memeeditplan.md` and writes
`memeeditplan.otio` — one still-image clip per meme, with gaps between them so
each lands at its timestamp. Drop it on a track above your video.

Two things to know about the plan format:

- The **SRT Time** column is a range (`00:00:00 - 00:00:06`). Only the *start* is
  used to position the meme; the end is just context. Duration comes from the
  **Duration** column.
- The `**Video:** ... (54m 37s)` duration in the header sets the total timeline
  length. If it's short, memes past that point get cut off — so it has to match
  your actual edit, not the example file's.

# Step 6 [06_Final] :
Run the .bats in order:

- `A_AskAIToPickHighlights.bat` — asks the AI to pick 3 moments out of
  `04_FinalSubtitle.srt` for a cold open, and writes `highlights.md`.
  Open it and tweak the timestamps. **Optional** — skip it and there is simply
  no cold open.
- `B_CombineFinalTimelines.bat` — accumulates the three stage timelines
  (`03\editplan.otio`, `04\FinalSubtitle.otio`, `05\memeeditplan.otio`) into
  `FinalTimelineNoCap.otio` and `FinalTimelineWithCap.otio`.
  Track order is V1 edit, V2 memes, V3 captions, plus A1 from the edit.
- `C_ConvertFinalTimelinesToFCPXML.bat` — writes `.fcpxml` next to each
  `.otio`, for importing into Resolve as a timeline.
- `D_ExportToCapCut.bat` — builds a CapCut draft project straight into CapCut's
  drafts folder. Open CapCut afterwards and it shows up under Projects.

The stages don't have to share a frame rate — the meme converter defaults to
30fps while the edit and captions are 60fps. A takes the edit's rate as the
master and resamples the rest onto it, so nothing drifts.

For Resolve, import either format with:
File > Import > Timeline > Import AAF, EDL, XML...

## Step 6B [06_Final] - the cold open:
When `highlights.md` exists, B builds a lead-in in front of everything:

    [highlight 1][highlight 2][highlight 3][intro][ ---- the whole edit ---- ]

and shifts the memes, captions and audio right by the same amount, so nothing
drifts out of sync. The edit itself is untouched — those moments still play
again in place when the video gets there.

Times in `highlights.md` are in **final cut time** — the same clock the SRT
uses, i.e. what you see watching the edited video, not source-tape time. The
Cut Time range IS the clip. B maps each range back to the right in-point in the
source footage, splitting a highlight in two if it happens to straddle one of
the edit's cuts.

Memes and captions sitting over a highlighted moment are carried into the cold
open with it, so a joke keeps its meme. That means a meme can appear twice in
the finished video, once in the cold open and once in place — that is intended.

The intro is `E:\AdamsRoadTrips\.Assets\AdamRoadTrips Intro.mp4` (4s, video
only, so the audio track gets 4s of silence under it). Override with
`--intro`, or use `--no-intro` to build without a cold open while keeping
`highlights.md` around.

## Step 6A [06_Final] - notes on the CapCut export:
C uses the **NoCap** timeline on purpose. The captions are one clip per word
(~3000 of them), which makes an unusable CapCut timeline, and CapCut has its own
caption tools that do a better job. Use `--with-captions` if you really want
them.

The CapCut project is named after the project folder. Override it with:
`python .scripts\ExportToCapCut.py --name "SnowRunner Part 02"`

Other flags worth knowing: `--dry-run` (report only), `--force` (overwrite an
existing project of the same name), `--drafts-root` (if CapCut is installed
somewhere non-standard).

The heavy lifting is `.scripts\fcpxml_to_capcut2.py`, which came from
`.WritingDaviniciXMLtoOTIO`. Two things it needs that plain FCPXML does not
give it, both handled automatically by `ExportToCapCut.py`:

- it reads the media path from `src` on `<asset>`, while Resolve reads the
  `<media-rep>` child — `OTIOtoFCPXML.py` writes both
- it treats a missing `lane` as lane 1, which would collide with the first
  overlay, so the export re-emits with `--lane-base 2`
