@echo off
setlocal

cd /d "%~dp0"

echo =====================================
echo Iniciando Hub WhatsApp RB (Uvicorn)
echo Host: 0.0.0.0  Porta: 3000
echo Para parar, feche esta janela.
echo =====================================

:restart
py -m uvicorn main:app --host 0.0.0.0 --port 3000 --no-use-colors

echo.
echo [%date% %time%] Processo finalizado. Reiniciando em 5 segundos...
timeout /t 5 /nobreak >nul
goto restart