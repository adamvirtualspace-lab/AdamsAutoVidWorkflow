# AdamsAutoVidWorkflow
### Welcome! This is Just My personal workflow to automate my gameplay video creation longform and shortform
## And so far, the Plans are here :

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
Assemble in your editor: the cut video, `04_FinalSubtitle\FinalSubtitle.otio` for
captions, and `05_Memes\memeeditplan.otio` for the memes. Export the result to
`06_Final\` as `FinalTimelineNoCap.otio` / `FinalTimelineWithCap.otio`.

TODO: this step is still manual — there's no script for it yet.
