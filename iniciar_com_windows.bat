@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\Atendimentos com IA.lnk'); $s.TargetPath='%~dp0iniciar.bat'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=7; $s.Save()"
echo Pronto: o sistema vai iniciar automaticamente (minimizado) quando o Windows ligar.
echo Para desfazer, apague o atalho "Atendimentos com IA" na pasta Inicializar (Win+R, shell:startup).
pause
