@echo off
rem PedroAI (trackmania-ai) Windows launcher.
rem   tmai                 run the AI: resume the latest run (or start one) and open the viewer
rem   tmai new             start a new run
rem   tmai check | install-plugin | train | smoke-test   (tmai --help)
setlocal
set "TMAI_ROOT=%~dp0"
set "HF_HOME=%TMAI_ROOT%.cache\huggingface"
set "TMENV_DOTNET=%TMAI_ROOT%tools\dotnet\dotnet.exe"
set "PYTHONWARNINGS=ignore::FutureWarning,ignore::UserWarning"
"%TMAI_ROOT%.venv\Scripts\python.exe" "%TMAI_ROOT%tmai.py" %*
rem Double-clicked: keep the window open to read the last messages
if "%~1"=="" pause
endlocal
