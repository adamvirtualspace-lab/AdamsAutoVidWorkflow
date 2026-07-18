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
In new cmd, go into the directory
`cd /d E:\AdamsRoadTrips\.EDITPLANtoOTIO` or in powershell `cd E:\AdamsRoadTrips\.EDITPLANtoOTIO`
then execute the python like
`python EditPlanToOTIO.py [editplan.md target]`
example:
`python EditPlanToOTIO.py E:\AdamsRoadTrips\SnowRunnerPart02\03_EditPlanToOtio\editplan.md`

# Step 4 [04_FinalSubtitle] :
Open the .otio in Davinci or Kdenlive, or other software. then generate the subtitle once more to
`04_FinalSubtitle\SR02_Shorter.srt

# Step 5 [05_Memes] :
Use an AI and use prompt something like this : 

hi, from current directory, inside it can you see `\04_FinalSubtitle\04_FinalSubtitle.srt` ? please understand the context from the subtitle, and please decide what memes should be appropriate on each funny or interesting moments according to the srt. and write the editplan like the format of `\05_Memes\.scripts\memeeditplan_example.md` also download all the necessary memes jpegs or png and put it all in this folder ( `\05_Memes\.memes\`) then write the edit plan in current directory, as `\05_Memes\memeeditplan.md` for grabbing the memes of the internet, can just use any tools available at your disposal. you are on windows btw, so don't use bash. use shell commands. also maybe use searxng for search if you have trouble. if you have vision, please check at the images you downloaded, make sure its valid as an image. not "that this images is no longer available or something.

## Step 5A [05_Memes] - Creating the meme timelines:
