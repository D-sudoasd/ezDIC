ezDIC v0.1.0 使用说明
======================

Developer
---------
ezDIC was developed by Dr. Delun Gong.

System Requirements
-------------------
- Windows 10/11 x64.
- Python is not required on the user's computer.
- Administrator permission is not required for normal use.

How To Run
----------
1. Extract the full ezDIC_Windows_x64 folder from the zip package.
2. Open the extracted folder.
3. Double-click ezDIC.exe.

Important
---------
Do not copy ezDIC.exe alone. The _internal folder and the notice/version files must stay with ezDIC.exe.

Basic Workflow
--------------
1. Select the image folder.
2. Select or confirm the output folder.
3. Load the image sequence.
4. Set the start and end frames.
5. Select strain direction and tracking mode.
6. Draw ROI 1 and ROI 2, then add the ROI group.
7. Click Start Analysis and Export.

Default Output
--------------
By default, ezDIC exports:
- Origin-compatible TXT files with Frame, EngineeringStrain, and TrueStrain.
- Engineering strain PNG plots.
- QC summary TXT.

Optional debug outputs such as full CSV files, correlation plots, overlays, and parameter summaries are disabled by default and can be enabled in the export options.

Attribution And Usage Notice
----------------------------
This software was developed by Dr. Delun Gong for lightweight extraction of linear strain from image sequences.

Users are not permitted to:
1. claim that they developed this software;
2. remove or alter the developer attribution;
3. redistribute, copy, forward, or share this software with unauthorized users;
4. use this software outside the authorized research or teaching context.

If you need to share or reuse this software, please obtain permission from Dr. Delun Gong first.

Security Notice
---------------
This first release is not code-signed. Windows Defender or SmartScreen may show an unknown publisher warning on some computers.
