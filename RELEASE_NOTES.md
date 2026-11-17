# FocusMic 0.1.1

多语言与设备体验更新 · Languages and device-picker update.

FocusMic 用摄像头看嘴型、麦克风听声音，在本地把目标说话人的声音从同一房间的多人说话中分离出来。  
FocusMic uses camera lip motion and microphone audio to extract the target speaker locally, even when other people in the room are talking.

## 下载 / Downloads

| 文件 / File | 大小 / Size | 用途 / Purpose |
|---|---:|---|
| `FocusMic-Runtime-2.9.1-cu128.exe` | 1.72 GiB | 先安装；PyTorch 2.9.1 + CUDA 12.8 运行时（与 0.1.0 相同） / install first (unchanged from 0.1.0) |
| `FocusMic-Setup-0.1.1.exe` | 242.1 MB | 再安装；主程序 / install second |
| `SHA256SUMS.txt` | 1 KB | 校验和 / checksums |
| VB-CABLE (external) | — | 官方下载 / official download: https://vb-audio.com/Cable/ |

两个安装包都是当前用户安装，不需要管理员权限。已经安装过 0.1.0 运行时的用户只需安装新的主程序。

Both installers are per-user and do not require administrator rights. If you already installed the 0.1.0 runtime, only the new main app is needed.

## 中文

### 这个版本新增

- **10 种界面语言**：简体中文、繁體中文、English、日本語、한국어、Español、Français、Deutsch、Português (Brasil)、Русский。
- 设置页新增“语言”，可选“跟随系统”；首次向导顶部也能直接选择语言。
- 空闲时切换语言立即生效；正在分离时会在停止后应用，当前页面和运行日志保留。
- **麦克风列表去重**：默认只显示 WASAPI 接口，合并 MME/DirectSound/WASAPI/WDM-KS 的同名重复项；设置里可开启“显示所有音频接口”。
- **摄像头信息**：下拉显示设备名、首选分辨率和帧率，例如 `HD Webcam · 1280×720 · 30 fps`。
- 针对德语、俄语、日语等长文本调整了侧边栏宽度、设置底栏、预览提示、频谱图和报告空状态的换行。

### 安装顺序

1. 安装 [VB-CABLE](https://vb-audio.com/Cable/) 虚拟声卡（官方下载，需单独安装）。
2. 安装 `FocusMic-Runtime-2.9.1-cu128.exe`。如果已经安装过 0.1.0 的运行时，可以跳过。
3. 安装 `FocusMic-Setup-0.1.1.exe`。
4. 首次启动选择麦克风和摄像头。
5. 在语音/会议软件里把麦克风选为 **CABLE Output**，关闭其降噪、AGC 和回声消除。

### 已知限制

- 需要正脸和可见的嘴部；侧脸、遮挡、强逆光会影响效果。
- 同音色、目标明显更轻、强混响仍然困难。
- 端到端约 0.3–0.5 s（不含语音软件自身缓冲）。
- 仅 Windows 10/11 x64 + NVIDIA CUDA 12.8。
- VB-CABLE 不随应用分发；安装包未签名。
- 麦克风为立体声时目前只取第 0 通道。

## English

### What's new

- **10 UI languages**: Simplified/Traditional Chinese, English, Japanese, Korean, Spanish, French, German, Brazilian Portuguese and Russian.
- A new Language setting (including Follow system) and a language picker in the first-run wizard.
- Language changes apply immediately while idle; during separation they apply after stopping, preserving the current page and logs.
- **Microphone de-duplication**: only WASAPI endpoints are shown by default, collapsing duplicate MME/DirectSound/WASAPI/WDM-KS entries. All interfaces can be enabled in Settings.
- **Camera details**: the picker shows the device name, preferred resolution and frame rate, e.g. `HD Webcam · 1280×720 · 30 fps`.
- Long-text layout fixes for German, Russian, Japanese and other languages across the sidebar, settings footer, preview hints, spectrum legend and report empty states.

### Install order

1. Install the [VB-CABLE](https://vb-audio.com/Cable/) virtual audio driver (official download, installed separately).
2. Install `FocusMic-Runtime-2.9.1-cu128.exe`. If the 0.1.0 runtime is already installed, skip this step.
3. Install `FocusMic-Setup-0.1.1.exe`.
4. On first launch, select your microphone and camera.
5. In your voice/meeting app, select **CABLE Output** as the microphone and
   disable its noise suppression, AGC and echo cancellation.

### Known limitations

- A frontal face and visible mouth are required; profile angles, occlusion and
  strong backlight degrade the visual branch.
- Similar voices, a much quieter target and strong reverberation remain hard.
- End-to-end latency is about 0.3–0.5 s, excluding the receiving app's buffer.
- Windows 10/11 x64 + NVIDIA CUDA 12.8 only.
- VB-CABLE is not bundled; installers are unsigned.
- Stereo microphones currently use channel 0 only.

## 校验 / Checksums

```text
e25fcc40098ba4104ea95213fe2a3761ae7cca457191814265783a33146cc85a  FocusMic-Setup-0.1.1.exe
70470a027728523e83d293c8e58d1988d2053da569b4f296c59a1a901a623af6  FocusMic-Runtime-2.9.1-cu128.exe
```

完整说明请见仓库 README；使用前请阅读“已知限制”和“隐私”部分。  
See the repository README for full details, requirements, performance numbers and
privacy notes.
