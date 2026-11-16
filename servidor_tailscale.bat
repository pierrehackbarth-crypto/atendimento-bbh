@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  THANOS - publicar no Tailscale (so para a rede do escritorio)
echo ============================================================
if not exist ".venv\Scripts\python.exe" (echo Rode primeiro o instalar.bat & pause & exit /b 1)
set "TS=tailscale"
where tailscale >nul 2>nul || set "TS=%ProgramFiles%\Tailscale\tailscale.exe"
"%TS%" status >nul 2>nul || (
  echo O Tailscale nao esta instalado ou nao esta conectado neste computador.
  echo 1. Baixe em https://tailscale.com/download e instale.
  echo 2. Entre com a conta do escritorio.
  echo 3. Rode este arquivo de novo.
  pause & exit /b 1
)
echo Ativando o cookie seguro (o acesso passa a ser por HTTPS)...
powershell -NoProfile -Command "$p='.env'; $t=Get-Content $p -Raw; $t=$t -replace '(?m)^SESSION_COOKIE_SECURE=.*$','SESSION_COOKIE_SECURE=true'; Set-Content -Path $p -Value $t -NoNewline -Encoding UTF8"
echo Publicando o sistema dentro da rede Tailscale (HTTPS)...
"%TS%" serve --bg http://127.0.0.1:8000
if errorlevel 1 (
  echo.
  echo Se apareceu um link pedindo para ativar HTTPS, abra-o, clique em ativar
  echo e rode este arquivo de novo.
  pause & exit /b 1
)
echo.
"%TS%" serve status
echo.
echo Configurando para o sistema abrir sozinho quando o Windows ligar...
call "%~dp0iniciar_com_windows.bat"
echo.
echo ============================================================
echo  Pronto. O endereco do sistema e o https://... mostrado acima.
echo  Ele so abre em computadores e celulares com o Tailscale
echo  ligado e conectados a conta do escritorio.
echo  Deixe este computador ligado e sem entrar em suspensao.
echo ============================================================
pause
