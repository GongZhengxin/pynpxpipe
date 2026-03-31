@echo off
REM 启动配置编辑器GUI
REM 自动激活 conda 环境并运行

echo Starting PyNeuralPipe Config Editor...
echo.

REM 激活 conda 环境
call conda activate dataprocess

REM 运行 GUI
python config_editor_gui.py

pause

