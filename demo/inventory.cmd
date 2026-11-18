@echo off
setlocal
"%~dp0..\runtime\python\python.exe" -X utf8 -m skill_inventory.cli %*
