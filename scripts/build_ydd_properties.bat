@echo off
setlocal EnableExtensions

set "VSROOT="
for %%V in (
  "%ProgramFiles%\Microsoft Visual Studio\18\Enterprise"
  "%ProgramFiles%\Microsoft Visual Studio\18\BuildTools"
  "%ProgramFiles%\Microsoft Visual Studio\2022\Enterprise"
  "%ProgramFiles%\Microsoft Visual Studio\2022\BuildTools"
  "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\BuildTools"
) do if not defined VSROOT if exist "%%~V\Common7\Tools\VsDevCmd.bat" set "VSROOT=%%~V"
if not defined VSROOT (
  echo ERROR: Visual C++ x64 tools not found.
  exit /b 1
)

call "%VSROOT%\Common7\Tools\VsDevCmd.bat" -no_logo -arch=x64 -host_arch=x64 2>nul
if errorlevel 1 exit /b 1

if not exist "build\YddProperties" mkdir "build\YddProperties"
cl /nologo /std:c++17 /EHsc /O2 /W4 /DUNICODE /D_UNICODE /LD ^
  "shell\YddProperties\YddProperties.cpp" ^
  /Fo"build\YddProperties\YddProperties.obj" ^
  /link /NOLOGO /OUT:"build\YddProperties\YddProperties.dll" ^
  /DEF:"shell\YddProperties\YddProperties.def" ^
  /IMPLIB:"build\YddProperties\YddProperties.lib" ^
  /PDB:"build\YddProperties\YddProperties.pdb" ^
  ole32.lib propsys.lib shlwapi.lib advapi32.lib
if errorlevel 1 exit /b 1

echo Built build\YddProperties\YddProperties.dll
exit /b 0
