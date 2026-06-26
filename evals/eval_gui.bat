@echo off
rem Double-click to open the eval GUI with no console window.
rem Uses pythonw (windowed Python) so nothing terminal-based appears.
start "" pythonw "%~dp0gui.py"
