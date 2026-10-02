@echo off
REM Launch the MotoGP de Bosch manager (Windows).
REM On first run, creates a virtualenv in .venv and installs the package (requires internet once).
cd /d "%~dp0"

if not exist .venv (
  echo First run: installing dependencies ^(internet connection needed only this time^)...
  py -3 -m venv .venv || goto :error
  .venv\Scripts\pip install -q -e . || goto :error
)

.venv\Scripts\streamlit run src\motogp_bosch\app.py --browser.gatherUsageStats false
goto :eof

:error
echo Installation failed. Make sure Python 3 is installed from python.org.
pause
exit /b 1
