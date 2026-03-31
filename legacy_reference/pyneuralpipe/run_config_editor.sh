#!/bin/bash
# 启动配置编辑器GUI
# 自动激活 conda 环境并运行

echo "Starting PyNeuralPipe Config Editor..."
echo ""

# 激活 conda 环境
source activate dataprocess

# 运行 GUI
python config_editor_gui.py

