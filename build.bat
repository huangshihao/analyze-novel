@echo off
setlocal
echo Installing dependencies...
pip install -r requirements.txt -r requirements-dev.txt || goto :err
echo Building exe...
pyinstaller --clean pyinstaller.spec || goto :err
echo.
echo ========================================
echo Build OK: dist\analyze-novel.exe
echo ========================================
exit /b 0

:err
echo Build FAILED
exit /b 1
