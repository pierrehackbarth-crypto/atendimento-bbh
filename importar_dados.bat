@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo Rode primeiro o instalar.bat & pause & exit /b 1)
echo Importando a base de clientes e o backup das fichas que estiverem nesta pasta...
set "ACHOU="
for %%F in (base_clientes*.json.gz fichas-backup*.json) do (
  set "ACHOU=1"
  echo  - %%F
  ".venv\Scripts\python.exe" -m app.cli import-ficha "%%F"
)
if not defined ACHOU echo Nenhum arquivo encontrado. Copie base_clientes_ficha.json.gz e fichas-backup-....json para esta pasta.
pause
