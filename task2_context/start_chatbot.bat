@echo off
rem COMMAND 1: switch the chatbot on.
cd /d "%~dp0"
".venv\Scripts\python.exe" chat.py %*
