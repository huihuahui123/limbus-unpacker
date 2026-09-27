@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title 边狱巴士解包器  作者: 得捕牢勒

cd /d "%~dp0"

echo.
echo   边狱巴士解包器  作者: 得捕牢勒
echo   默认输出到本程序所在目录下的 LCB_Unpacked
echo.

rem 优先使用打包好的 exe（无需 Python 环境）；没有就回退到脚本
if exist "%~dp0边狱巴士解包器.exe" (
  echo   正在启动 边狱巴士解包器.exe ...
  echo.
  "%~dp0边狱巴士解包器.exe"
  goto :end
)

set "VENV=C:\Users\123\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
set "PY=%VENV%"
if not exist "%VENV%" set "PY=python"

echo   未找到 exe，改用 Python 脚本运行
echo.
"%PY%" "%~dp0lcb_unpack.py"

:end
echo.
echo   运行结束。按任意键关闭窗口。
pause >nul
endlocal
