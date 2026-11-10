# 离屏三角形渲染器

这是从零实现渲染管线的初始工作区。`renderer` 仅提供命令行入口，尚无渲染实现；`scenes` 和 `assets` 均为自建合成输入。完整行为以 [contract.md](contract.md) 为准。

## 环境

Windows x64、Python 3.13；已提供 Pillow 12.3.0 的 Windows CPython 3.13 wheel，不需要显卡、外部服务或网络。

在本目录使用 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-index --find-links vendor -r requirements.txt
.\.venv\Scripts\python.exe checks\check_inputs.py
```

其他操作系统可使用 Python 3.13 并从对应软件源安装 `requirements.txt`；随附 wheel 仅供上述 Windows 环境使用。Pillow 仅用于图像读写；核心几何处理、裁剪、光栅化、深度测试、混合与采样须自行实现。运行依赖限 Python 标准库与 Pillow。

## 实现与运行

```powershell
.\.venv\Scripts\python.exe -m renderer --scene scenes\05_transparency.json --output outputs\transparency --samples 4
.\.venv\Scripts\python.exe checks\check_render.py
```

首次渲染命令退出码为 2，并提示尚未实现；这是预期起点。实现后每次调用写出 `color.png`、`depth.f32` 和 `ids.u32`。后两者均为从上到下、从左到右的紧密数组；格式及拾取规则见契约。`outputs` 用于本地结果，不属于初始素材。

`checks/check_render.py` 是公开的黑盒验收脚本，会调用实际入口。它使用解析探针和不变量检查，不包含完整参考渲染器。通过脚本不能代替契约要求的全部功能；各场景的用途见 `scenes/README.txt`。交付实现代码、必要测试及更新后的启动说明。

## 文件

- `prompt.txt`：题面。
- `contract.md`：输入、输出及渲染行为。
- `scenes/`、`assets/`：输入场景与线性 RGBA 纹理。
- `renderer/`：未实现的入口。
- `checks/`：素材检查与公开验收。
- `requirements.txt`、`vendor/`：固定依赖及离线安装包；第三方许可保留于 wheel 内。
