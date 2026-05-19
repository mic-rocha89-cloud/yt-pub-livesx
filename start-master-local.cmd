@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
set "GWS_CONFIG_DIR=%~dp0config"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "LOG_FILE=%~dp0master-dashboard\master-local.log"

if not exist "%PYTHON_EXE%" (
  echo [ERRO] Python da venv nao encontrado em:
  echo %PYTHON_EXE%
  echo.
  echo Rode a instalacao local antes de iniciar o master-dashboard.
  pause
  exit /b 1
)

echo Iniciando master-dashboard local em http://127.0.0.1:8090/login
echo Logs: %LOG_FILE%
echo.

"%PYTHON_EXE%" -u "master-dashboard\server.py" >> "%LOG_FILE%" 2>&1

echo.
echo Master-dashboard encerrado. Consulte o log acima para detalhes.
pause
