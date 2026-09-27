@echo off
chcp 65001 >nul
title 重新打包 边狱巴士解包器
cd /d "%~dp0"

set "PY=C:\Users\123\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

set "NAME=边狱巴士解包器"

echo.
echo   正在打包，请稍候（约 30 秒）...
echo.

"%PY%" -m PyInstaller --onefile --console --name "%NAME%" --noconfirm ^
  --collect-submodules UnityPy --collect-data UnityPy ^
  --collect-submodules fmod_toolkit --collect-data fmod_toolkit ^
  --collect-submodules archspec --collect-data archspec ^
  lcb_unpack.py

if exist "dist\%NAME%.exe" (
  copy /y "dist\%NAME%.exe" "%NAME%.exe" >nul
  echo.
  echo   打包完成: %~dp0%NAME%.exe
) else (
  echo.
  echo   打包失败，请检查上方输出。
)

echo.
echo   按任意键关闭。
pause >nul
