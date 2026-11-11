@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo Rode primeiro o instalar.bat & pause & exit /b 1)
title Atendimentos com IA - servidor (nao feche esta janela)
echo Atendimentos com IA rodando em http://localhost:8000
echo Mantenha esta janela aberta enquanto usar o sistema. Para encerrar, feche-a.
start "" cmd /c "timeout /t 4 /nobreak >nul & start http://localhost:8000"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning
pause
