@echo off
rem HomeNOC: demonstracao com uma rede simulada (nao toca na sua rede).
chcp 65001 >nul
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python nao encontrado.
  echo Instale pelo site python.org/downloads marcando "Add python.exe to PATH" e tente de novo.
  pause
  exit /b 1
)
%PY% -m homenoc --demo --porta 8770 %*
if errorlevel 1 pause
