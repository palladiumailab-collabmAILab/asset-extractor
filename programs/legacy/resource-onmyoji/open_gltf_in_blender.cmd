@echo off
setlocal
set "BLENDER=C:\Users\palla\Documents\resource\OnmyojiAPK\tools\blender\Blender 5.2.1\blender-5.2.1-windows-x64\blender.exe"
set "IMPORTER=C:\Users\palla\Documents\resource\OnmyojiAPK\tools\open_gltf_in_blender.py"
"%BLENDER%" --python "%IMPORTER%" -- "%~1"
endlocal
