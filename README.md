# BioHD-C20 macOS viewer

在 macOS 上预览 BioHD-C20 USB 显微镜相机的轻量工具。支持实时画面、自动/手动曝光、增益、一键白平衡、色温/Tint、色相、饱和度、亮度、对比度、Gamma、曝光目标、平场/暗场校正和保存当前帧。

> 社区兼容项目，与 BioHD、FluoCa 或 ToupTek 无隶属关系。目前仅针对 USB ID `0547:f556`（USB 3）和 `0547:f557`（USB 2）验证。

## 安装

要求：macOS、Python 3、Xcode Command Line Tools，以及约 300 MB 临时下载空间。

1. 下载并解压本仓库。
2. 双击 `setup.command`。它会从 ToupTek 官方下载稳定版 ToupCam SDK、提取 macOS 运行库，并在本机编译兼容层。
3. 双击 `run.command`。浏览器会打开 `http://127.0.0.1:8765`。

若 macOS 阻止首次双击，可在“系统设置 → 隐私与安全性”中允许，或在终端运行：

```sh
./setup.command
./run.command
```

## 白平衡

先移开样品，让均匀照明的空白视野充满画面，再点击“一键白平衡”。不要对着有颜色的样品校准，否则样品颜色会被错误中和。

## 颜色与视野校正

展开“FLUOCA 风格高级色彩控制”可调整相机 SDK 原生 ISP 参数。若目标是接近目镜观感，先恢复中性默认值，再依次调白平衡、曝光、Gamma/对比度，最后微调饱和度。BioHD-C20 的 USB 2.0 固件不提供独立 RGB 增益接口，因此不显示该项。

- 平场校正：移开样品，保留当前照明和焦点后采集，用于减轻暗角与照明不均。
- 暗场校正：完全盖住镜头，并保持实际拍摄使用的曝光和增益后采集，用于减轻固定图样与热像素。

## 工作方式与隐私

- 预览服务只监听本机回环地址 `127.0.0.1`，不上传图像、没有遥测。
- 兼容层只在当前进程中映射设备型号并补齐 OEM 固件与通用 SDK 间的 8 字节帧尾差异；不刷写固件、不安装内核扩展、不修改系统文件。
- ToupCam SDK 不包含在本仓库中；安装脚本从[官方 SDK 下载中心](https://www.touptekphotonics.com/download/?category=SDK)获取。该 SDK 受其供应商条款约束，不属于本项目 MIT 许可证范围。

## 自检

连接相机后运行：

```sh
./run.command --check
```

成功时会在本地生成 `last-frame.jpg`（已被 `.gitignore` 排除）。

## License

本仓库原创代码采用 MIT License。第三方 ToupCam SDK 及其 Python 封装仍归各自权利人所有。
