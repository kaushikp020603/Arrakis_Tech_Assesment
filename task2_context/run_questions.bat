@echo off
rem COMMAND 2 (master): run every question in questions.md and save outputs\answers.json
cd /d "%~dp0"
".venv\Scripts\python.exe" run_questions.py %*
