@echo off

cd /d "%~dp0"
echo asking ai to make editplan based on raw subtitle on "02_RawSubtitles"
python .scripts_and_examples\askaitoeditplan.py

echo converting the editplan to otio format
python .scripts_and_examples\EditPlanToOTIO.py editplan.md -o editplan.otio

echo ___

echo Check the editplan.md using ur text editor and try load the editplan.otio into your video editor
echo _
echo Can edit the editplan.md using ur text editor by changing "KEEP" to "CUT" or vice versa then run the "B_Convert_EditPlan_To_OTIO.bat"
echo _
echo if everything is ok, can render the audio using the .bat and continue on the 04 Folder

echo.


pause
endlocal
