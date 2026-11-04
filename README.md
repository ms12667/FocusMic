# FocusMic

**Local, real-time audio-visual target speaker extraction for Windows**  
**Windows 本地实时音视频目标说话人提取**

[中文](#中文) · [English](#english) · [Releases](https://github.com/ms12667/FocusMic/releases) · [License](LICENSE)

FocusMic uses the camera to see who is speaking and the microphone to hear
what is being said. It extracts **your** voice from a room where other people
are talking at the same time, locally on your own GPU, and sends the result to
a virtual audio cable for voice or meeting apps.

---

## 中文

### FocusMic 是什么

FocusMic 是一个 Windows 桌面应用：摄像头看嘴型，麦克风听声音，实时把你自己的声音从同一房间的多人说话中分离出来。

它不是“把麦克风音量调小”，也不是“识别到人声就保留”。它用视觉信息判断**画面里哪个人在说话**，再把音频里属于这个人的部分重建出来。分离结果通过 VB-CABLE 送给语音或会议软件，对方听到的是你，而不是整个房间。

适合这些场景：

- 宿舍、合租房、开放工位，旁边的人也在说话或开会；
- 麦克风离你较远，旁边的人反而更响；
- 传统降噪去掉了风扇和键盘，却对“另一个真实人声”无能为力。

### 效果

- 保留目标说话人的声音，尽量压低同一画面/同一房间里的其他人声。
- 手遮住嘴、离开画面或目标丢失时，自动直通原始麦克风，避免突然“没声音”。
- 支持手动框选目标脸、重新锁定、全局旁路热键、托盘常驻、设备热插拔。
- Falcon Small 单窗推理约 **65–85 ms**；Falcon Big 约 **75 ms**。
- 内部同音色干扰测试：纯音频基线 SIR 约 **0.6 dB**，口型路线约 **15.1 dB**。
- 等响度合成素材：SI-SDR 约 **+3.3 dB**，SIR 约 **25.5 dB**。

这些是内部测试数字，不是对所有房间、所有麦克风、所有说话人的保证。光照、正脸角度、麦克风距离、房间混响和两个人的音色接近程度都会影响结果。

### 和传统降噪软件的区别

| 能力 | 传统降噪（RNNoise / Krisp / NVIDIA Broadcast 等） | FocusMic |
|---|---|---|
| 风扇、键盘、空调等稳态噪声 | 好 | 顺带抑制（模型只重建目标语音） |
| 旁边的人同时说话 | 基本无法区分 | 用嘴型锁定目标说话人 |
| 两个同音色的人 | 容易一起保留或一起压掉 | 视觉分支可以提供区分线索 |
| 需要摄像头 | 不需要 | 需要，且嘴部要可见 |
| 额外延迟 | 通常很低 | 约 0.3–0.5 s（不含接收端缓冲） |
| 主要解决的问题 | 噪声 | **多人同时说话时的目标选择** |

FocusMic 不是传统降噪器的替代品。它解决的是“房间里有两个真实人声，我要留下其中一个”的问题；对稳态噪声也会有帮助，因为模型只重建目标说话人的语音。

### 运行环境

| 项目 | 要求 |
|---|---|
| 系统 | Windows 10 / 11 x64 |
| GPU | NVIDIA 显卡，驱动支持 CUDA 12.8；已在 RTX 5070 Ti Laptop 12 GB 上验证 |
| 摄像头 | 能看到正脸和嘴部；普通 USB/内置摄像头即可 |
| 麦克风 | 任意 Windows 录音设备 |
| 虚拟声卡 | [VB-CABLE](https://vb-audio.com/Cable/)（官方下载，免费捐赠版；或等价虚拟音频线），需单独安装 |
| 磁盘 | 主程序约 590 MB；AI 运行时约 4.3 GB |
| 显存 | Falcon Small 约 384 MB；Falcon Big 约 567 MB |
| 内存 | 建议 8 GB 以上 |
| Python | 安装版不需要；从源码运行/构建需要 Python 3.12 |

### 性能开销

在 RTX 5070 Ti Laptop 12 GB + Ryzen 9 7945HX 上的实测：

| 项目 | Falcon Small | Falcon Big |
|---|---:|---:|
| 单窗推理（2 s 音频 + 50 帧口型） | 约 67.6 ms（p95 69.5 ms） | 约 74.8 ms（p95 76.9 ms） |
| 显存 | 约 384 MB（reserved 648 MB） | 约 567 MB（reserved 918 MB） |
| GPU 占用（0.2 s 步长） | 约 31% | 约 31–35% |

其他开销：

- MediaPipe 口型/手势跟踪约 **10.8 ms/帧**，25 fps 下约 **单核 27%**。
- 端到端延迟约 **0.3–0.5 s**，不含语音/会议软件自身的缓冲；应用内会实时显示“全链路延迟”估算。
- 推理只在本机进行，不需要上传音频或视频。

### 安装

1. 安装 [**VB-CABLE**](https://vb-audio.com/Cable/)（官方下载页；虚拟音频驱动，需单独安装）。
2. 从 [Releases](https://github.com/ms12667/FocusMic/releases) 下载两个文件：
   - `FocusMic-Runtime-2.9.1-cu128.exe`（PyTorch 2.9.1 + CUDA 12.8，约 1.72 GiB）
   - `FocusMic-Setup-0.1.0.exe`（主程序，约 235 MB）
3. 先运行运行时安装包，再运行主程序安装包。两者都是当前用户安装，不需要管理员权限。
4. 第一次启动会打开向导，选择麦克风和摄像头。
5. 在语音/会议软件里把麦克风选为 **CABLE Output**，并关闭它自带的降噪、AGC 和回声消除。

主程序不包含 PyTorch。没有安装运行时时，主页会显示提示横幅，点“开始分离”会打开安装引导，不会闪退。

安装包未签名，Windows SmartScreen 可能提示；这是正常现象。

### VB-CABLE 名称说明

> 官方下载 / Official download: https://vb-audio.com/Cable/
> 请从 VB-Audio 官方站点下载，避免第三方捆绑包 / Download from the official site to avoid bundled third-party installers.

Windows 对两个端点的分类容易让人困惑：

| Windows 分类 | 设备名 | 谁在用 |
|---|---|---|
| 播放 / Render / 扬声器 | **CABLE Input** | FocusMic 写入 |
| 录音 / Capture / 麦克风 | **CABLE Output** | 语音/会议软件选择 |

所以：FocusMic 写到 `CABLE Input`，语音软件从 `CABLE Output` 取麦克风。`CABLE Input` 不是录音设备，不能在语音软件里当麦克风选；如果它出现在列表里，那是播放设备列表。

### 使用

1. 正对摄像头，保证嘴部可见；避免强逆光和侧脸。
2. 点“开始分离”。控制台会显示模型加载、CABLE 输出和耳机监听设备。
3. 如果画面里有其他人脸，点“框选目标”在预览里框住自己的脸；点“重新锁定”可恢复自动选择。
4. 手遮嘴或按 `Ctrl+Alt+M` 可切到原始麦克风（旁路）；松开/再按恢复分离。
5. 关闭窗口默认最小化到托盘，分离继续运行；设置里可改成直接退出。托盘右键菜单可显示、开始/停止、旁路和退出。
6. 设置页可改主题、开机启动、全局热键、关闭行为和首次向导。

### 隐私

- 所有推理在本机完成，不上传摄像头画面或麦克风音频。
- 摄像头画面不保存；只提取嘴部区域用于推理。
- 没有遥测和账号系统。
- 日志只写到本机 `%LOCALAPPDATA%\FocusMic\logs`。
- 配置只写到本机 `%APPDATA%\FocusMic\config.json`。

### 已知限制

- 必须能看到正脸和嘴部；侧脸、遮挡、强逆光会让视觉分支失效。
- 同音色、目标比干扰轻很多、强混响仍然困难；这时建议靠近麦克风。
- 端到端不是“零延迟”：0.2 s 步长 + 模型/缓冲约 0.3–0.5 s，语音软件还会再加缓冲。
- 目前仅支持 Windows + NVIDIA CUDA；没有 CPU 实时路径。
- VB-CABLE 不随应用分发；安装器和应用都未签名。
- 安装器界面为英文，应用界面为中英混合。
- 麦克风为立体声时目前只取第 0 通道。
- 长时间运行可能有轻微音视频时钟漂移。
- 请只在你有权处理的音频上使用；不要用它进行未经同意的录音或监听。

### 从源码运行

需要 Python 3.12、NVIDIA 驱动和 `.venv` 中的依赖：

```bat
uv venv .venv
uv pip install --python .venv\Scripts\python.exe -r requirements-focusmic.txt
FocusMic.bat
```

或：

```bat
.venv\Scripts\python.exe -m focusmic
```

构建安装包：

```bat
build-windows.bat
build-runtime.bat
```

`build-windows.bat` 生成主程序和主安装器；`build-runtime.bat` 生成 PyTorch/CUDA 运行时安装包。运行时安装包编译约 15 分钟。

### 项目结构

```text
focusmic/                 native app package
  app.py / ui.py          single-instance entry + six-tab UI
  audio.py / video.py     WASAPI capture + camera/MediaPipe tracking
  pipeline.py             window scheduler + Falcon + safe bypass
  runtime.py              external PyTorch/CUDA locator + ABI/version checks
  output.py / monitor.py  CABLE output + headphone monitor
  vendor/falcon/          vendored Falcon inference (Apache-2.0)
  assets/                 icons + MediaPipe task files
weights/                  Falcon Small/Big checkpoints (Apache-2.0)
packaging/                PyInstaller/Inno Setup scripts
dist/                     release artifacts (gitignored)
```

### 许可证与致谢

FocusMic 以 **Apache-2.0** 发布。Falcon 代码与权重为 Apache-2.0；MediaPipe 为 Apache-2.0；PySide6 为 LGPL-3.0（动态链接）；Lucide 为 ISC；Simple Icons 为 CC0；VB-CABLE 是独立驱动，不随本应用分发。详见 `LICENSE`、`NOTICE` 和 `THIRD_PARTY_LICENSES.md`。

---

## English

### What is FocusMic?

FocusMic is a Windows desktop app that uses the camera to see who is
speaking and the microphone to hear what is being said. It extracts **your**
voice from a room where other people are talking at the same time, runs the
model locally on your GPU, and sends the result to a virtual audio cable for
voice or meeting apps.

It is not a volume gate and not a "keep any human voice" filter. It uses visual
information to decide **which person on camera is speaking**, then reconstructs
that person's speech from the audio. The receiving app hears you, not the whole
room.

Typical use cases:

- shared rooms, dorms, open offices, or anywhere another person is talking nearby;
- your microphone is farther away while the other person is louder;
- traditional denoising removes fans and keyboards but cannot separate two real
  human voices.

### What it does

- Keeps the target speaker and suppresses other voices in the same room.
- Falls back to the raw microphone when your mouth is covered, you leave the
  frame, or the target is lost, so you are never suddenly muted.
- Manual ROI selection, re-acquire, global bypass hotkey, tray mode, and device
  hot-plug support.
- Falcon Small inference is about **65–85 ms** per 2 s window; Falcon Big about
  **75 ms**.
- Internal same-voice test: audio-only baseline SIR about **0.6 dB**, lip-based
  route about **15.1 dB**.
- Equal-loudness synthetic material: SI-SDR about **+3.3 dB**, SIR about
  **25.5 dB**.

These are internal measurements, not guarantees for every room, microphone, or
pair of speakers. Lighting, face angle, microphone distance, reverberation and
voice similarity all matter.

### How it differs from noise suppression

| Capability | Traditional noise suppression (RNNoise / Krisp / NVIDIA Broadcast, etc.) | FocusMic |
|---|---|---|
| Fans, keyboards, stationary noise | Good | Incidental; the model reconstructs only the target speech |
| Another person talking at the same time | Cannot reliably separate | Uses lip motion to identify the target |
| Two similar voices | Often keeps or removes both | Visual branch provides a separation cue |
| Camera required | No | Yes; the mouth must be visible |
| Added latency | Usually low | About 0.3–0.5 s, excluding the receiving app's buffer |
| Main problem solved | Noise | **Target selection when multiple people speak** |

FocusMic is not a drop-in replacement for a denoiser. It solves the case where
two real human voices are present and you want to keep only one. It also helps
with stationary noise because it reconstructs only the target voice.

### Requirements

| Item | Requirement |
|---|---|
| OS | Windows 10 / 11 x64 |
| GPU | NVIDIA GPU with a CUDA 12.8-capable driver; tested on RTX 5070 Ti Laptop 12 GB |
| Camera | A camera that can see your face and mouth; a normal USB or built-in camera is enough |
| Microphone | Any Windows recording device |
| Virtual cable | [VB-CABLE](https://vb-audio.com/Cable/) (official download, donationware; or an equivalent virtual audio cable), installed separately |
| Disk | App about 590 MB; AI runtime about 4.3 GB |
| VRAM | About 384 MB (Falcon Small) / 567 MB (Falcon Big) |
| RAM | 8 GB+ recommended |
| Python | Not required for the installer; Python 3.12 is needed only to run/build from source |

### Performance

Measured on an RTX 5070 Ti Laptop 12 GB + Ryzen 9 7945HX:

| Item | Falcon Small | Falcon Big |
|---|---:|---:|
| Inference per window (2 s audio + 50 mouth frames) | ~67.6 ms (p95 69.5 ms) | ~74.8 ms (p95 76.9 ms) |
| VRAM | ~384 MB (reserved 648 MB) | ~567 MB (reserved 918 MB) |
| GPU utilization (0.2 s hop) | ~31% | ~31–35% |

Other overhead:

- MediaPipe mouth/hand tracking: ~10.8 ms/frame, about 27% of one CPU core at 25 fps.
- End-to-end latency is roughly 0.3–0.5 s, excluding the receiving app's buffer;
  the app shows a live full-chain estimate.
- Inference is fully local; no audio or video is uploaded.

### Install

1. Install [**VB-CABLE**](https://vb-audio.com/Cable/) (official download page; virtual audio driver, installed separately).
2. Download both files from [Releases](https://github.com/ms12667/FocusMic/releases):
   - `FocusMic-Runtime-2.9.1-cu128.exe` (PyTorch 2.9.1 + CUDA 12.8, about 1.72 GiB)
   - `FocusMic-Setup-0.1.0.exe` (main app, about 235 MB)
3. Run the runtime installer first, then the main installer. Both are per-user
   and do not require administrator rights.
4. On first launch, the wizard asks for your microphone and camera.
5. In your voice/meeting app, select **CABLE Output** as the microphone and
   disable its noise suppression, AGC and echo cancellation.

The main app does not bundle PyTorch. If the runtime is missing, the home page
shows a banner and the start button opens installation guidance instead of
crashing.

The installers are unsigned; Windows SmartScreen may show a warning.

### VB-CABLE naming

> Official download: https://vb-audio.com/Cable/
> Download from the official VB-Audio site to avoid bundled third-party installers.

Windows classifies the two endpoints in a way that is easy to get backwards:

| Windows class | Device name | Used by |
|---|---|---|
| Render / playback / speakers | **CABLE Input** | FocusMic writes here |
| Capture / recording / microphone | **CABLE Output** | Voice/meeting app selects this |

FocusMic writes to `CABLE Input`; the voice app takes `CABLE Output` as its
microphone. `CABLE Input` is not a recording endpoint and cannot be selected as
a microphone in the voice app. If it appears in a device list, that is the
playback list.

### Usage

1. Face the camera with your mouth visible; avoid strong backlight and profile angles.
2. Click Start. The console shows model loading, CABLE output and the headphone
   monitor device.
3. If other faces are in the frame, click **Select target** and drag a box
   around your face; **Re-acquire** returns to automatic selection.
4. Cover your mouth or press `Ctrl+Alt+M` to bypass to the raw microphone;
   uncover/press again to return to separation.
5. Closing the window hides FocusMic to the tray by default and separation
   continues. Settings can make × quit directly. The tray menu can show the
   window, start/stop, bypass, or quit.
6. Settings control theme, startup, global hotkey, close behavior, and the
   first-run wizard.

### Privacy

- All inference runs locally. Camera frames and microphone audio are not uploaded.
- Camera frames are not saved; only the mouth region is used for inference.
- No telemetry and no account system.
- Logs stay in `%LOCALAPPDATA%\FocusMic\logs`.
- Settings stay in `%APPDATA%\FocusMic\config.json`.

### Known limitations

- The face and mouth must be visible; profile angles, occlusion and strong
  backlight break the visual branch.
- Similar voices, a much louder interferer, and strong reverberation are still
  hard. Moving closer to the microphone helps more than any post-processing.
- Latency is not zero: 0.2 s hop plus model/buffering gives about 0.3–0.5 s, and
  the receiving app adds its own buffer.
- Windows + NVIDIA CUDA only; there is no real-time CPU path.
- VB-CABLE is not bundled; installers and the app are unsigned.
- The installer UI is English; the app UI is mixed Chinese/English.
- Stereo microphones currently use channel 0 only.
- Long sessions may show slight A/V clock drift.
- Use it only on audio you have the right to process. Do not use it for
  non-consensual recording or surveillance.

### Run from source

Requires Python 3.12, an NVIDIA driver, and the dependencies in `.venv`:

```bat
uv venv .venv
uv pip install --python .venv\Scripts\python.exe -r requirements-focusmic.txt
FocusMic.bat
```

Or:

```bat
.venv\Scripts\python.exe -m focusmic
```

Build the installers:

```bat
build-windows.bat
build-runtime.bat
```

`build-windows.bat` builds the app and main installer; `build-runtime.bat`
builds the PyTorch/CUDA runtime installer. The runtime installer takes about
15 minutes to compile.

### Project layout

```text
focusmic/                 native app package
  app.py / ui.py          single-instance entry + six-tab UI
  audio.py / video.py     WASAPI capture + camera/MediaPipe tracking
  pipeline.py             window scheduler + Falcon + safe bypass
  runtime.py              external PyTorch/CUDA locator + ABI/version checks
  output.py / monitor.py  CABLE output + headphone monitor
  vendor/falcon/          vendored Falcon inference (Apache-2.0)
  assets/                 icons + MediaPipe task files
weights/                  Falcon Small/Big checkpoints (Apache-2.0)
packaging/                PyInstaller/Inno Setup scripts
dist/                     release artifacts (gitignored)
```

### License and credits

FocusMic is released under **Apache-2.0**. Falcon code and weights are
Apache-2.0; MediaPipe is Apache-2.0; PySide6 is LGPL-3.0 (dynamic linking);
Lucide is ISC; Simple Icons is CC0; VB-CABLE is a separate driver and is not
bundled. See `LICENSE`, `NOTICE` and `THIRD_PARTY_LICENSES.md`.
