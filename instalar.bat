@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  Atendimentos com IA - instalacao (Buss ^& Hackbarth)
echo ============================================================
echo.
set "PY="
rem O "python" do Windows pode ser so um atalho para a Microsoft Store: testamos cada opcao de verdade.
call :testar py -3
if not defined PY call :testar python
if not defined PY call :testar "%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined PY call :testar "%LocalAppData%\Programs\Python\Python313\python.exe"
if not defined PY call :testar "%ProgramFiles%\Python312\python.exe"
if not defined PY (
  echo Python nao encontrado neste computador. Instalando Python 3.12 pelo winget...
  where winget >nul 2>nul && winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
  call :testar "%LocalAppData%\Programs\Python\Python312\python.exe"
)
if not defined PY (
  echo.
  echo Nao foi possivel instalar o Python automaticamente.
  echo 1. Abra https://www.python.org/downloads/ e baixe o Python 3.12 para Windows.
  echo 2. Na instalacao, marque "Add python.exe to PATH".
  echo 3. Rode este arquivo de novo.
  pause & exit /b 1
)
echo Usando: %PY%
if not exist ".venv\Scripts\python.exe" (
  echo Criando ambiente isolado...
  %PY% -m venv .venv || (echo Falha ao criar o ambiente. & pause & exit /b 1)
)
set "VPY=%~dp0.venv\Scripts\python.exe"
echo Instalando dependencias ^(pode levar alguns minutos^)...
"%VPY%" -m pip install --upgrade pip >nul
"%VPY%" -m pip install -r requirements.txt || (echo Falha ao instalar dependencias. Verifique a internet e tente de novo. & pause & exit /b 1)
if not exist ".env" (
  echo Gerando configuracao e chave de criptografia...
  "%VPY%" tools\gerar_env.py || (echo Falha ao gerar a configuracao. & pause & exit /b 1)
)
echo Preparando banco de dados...
"%VPY%" -m alembic upgrade head || (echo Falha ao preparar o banco. & pause & exit /b 1)
echo.
"%VPY%" tools\tem_usuario.py
if errorlevel 1 (
  echo Crie o primeiro usuario ^(administrador^):
  call "%~dp0criar_usuario.bat" admin
)
echo.
echo ============================================================
echo  Falta so um passo: informe a chave da OpenAI e o modelo de analise.
echo  O Bloco de Notas vai abrir o arquivo de configuracao (.env).
echo  Preencha OPENAI_API_KEY= e OPENAI_ANALYSIS_MODEL= , salve e feche.
echo ============================================================
pause
notepad ".env"
echo.
echo Instalacao concluida. Para usar, de dois cliques em "iniciar.bat".
pause
exit /b 0

:testar
%* -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 set PY=%*
exit /b 0
