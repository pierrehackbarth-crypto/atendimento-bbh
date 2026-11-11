@echo off
cd /d "%~dp0"
set "PAPEL=%~1"
if "%PAPEL%"=="" set /p PAPEL=Papel (admin, advogado ou assistente) [advogado]: 
if "%PAPEL%"=="" set "PAPEL=advogado"
set /p EMAIL=E-mail do usuario: 
set /p NOME=Nome completo: 
echo A senha precisa ter pelo menos 10 caracteres (nao aparece enquanto digita).
".venv\Scripts\python.exe" -m app.cli create-user "%EMAIL%" "%NOME%" %PAPEL%
pause
