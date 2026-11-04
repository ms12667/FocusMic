# FocusMic 0.1.0

首个公开版本 · First public release.

FocusMic 用摄像头看嘴型、麦克风听声音，在本地把目标说话人的声音从同一房间的多人说话中分离出来。  
FocusMic uses camera lip motion and microphone audio to extract the target speaker locally, even when other people in the room are talking.

## 下载 / Downloads

| 文件 / File | 大小 / Size | 用途 / Purpose |
|---|---:|---|
| `FocusMic-Runtime-2.9.1-cu128.exe` | 1.72 GiB | 先安装；PyTorch 2.9.1 + CUDA 12.8 运行时 / install first |
| `FocusMic-Setup-0.1.0.exe` | 234.6 MB | 再安装；主程序 / install second |
| `SHA256SUMS.txt` | 1 KB | 校验和 / checksums |

两个安装包都是当前用户安装，不需要管理员权限。  
Both installers are per-user and do not require administrator rights.

## 中文

### 安装顺序

1. 安装 VB-CABLE 虚拟声卡（需单独下载）。
2. 安装 `FocusMic-Runtime-2.9.1-cu128.exe`。
3. 安装 `FocusMic-Setup-0.1.0.exe`。
4. 首次启动选择麦克风和摄像头。
5. 在语音/会议软件里把麦克风选为 **CABLE Output**，关闭其降噪、AGC 和回声消除。

### 这个版本包含

- 本地 Falcon 音视频目标说话人提取，Falcon Small 默认，Big 可选。
- 摄像头预览、手动框选目标、重新锁定、手遮嘴/丢失目标自动直通。
- 原生 CABLE 输出、耳机监听（跟随 Windows 当前默认播放设备）。
- 性能信息、运行报告、中英双语关于页、深色/浅色主题。
- 关闭窗口默认最小化到托盘，设置里可改为直接退出。
- 麦克风按设备名 + host API 持久化；CABLE 输出、设备热插拔、首次向导。
- 主程序不包含 PyTorch；运行时缺失时会显示安装引导，不会闪退。

### 已知限制

- 需要正脸和可见的嘴部；侧脸、遮挡、强逆光会影响效果。
- 同音色、目标明显更轻、强混响仍然困难。
- 端到端约 0.3–0.5 s（不含语音软件自身缓冲）。
- 仅 Windows 10/11 x64 + NVIDIA CUDA 12.8。
- VB-CABLE 不随应用分发；安装包未签名。
- 麦克风为立体声时目前只取第 0 通道。

## English

### Install order

1. Install the VB-CABLE virtual audio driver (separate download).
2. Install `FocusMic-Runtime-2.9.1-cu128.exe`.
3. Install `FocusMic-Setup-0.1.0.exe`.
4. On first launch, select your microphone and camera.
5. In your voice/meeting app, select **CABLE Output** as the microphone and
   disable its noise suppression, AGC and echo cancellation.

### What's in this release

- Local Falcon audio-visual target speaker extraction; Falcon Small by default,
  Big selectable.
- Camera preview, manual target ROI, re-acquire, automatic bypass when the mouth
  is covered or the target is lost.
- Native CABLE output and headphone monitoring that follows the current Windows
  default playback endpoint.
- Performance page, run report, bilingual About page, dark/light themes.
- Closing the window hides to the tray by default; Settings can make × quit.
- Microphone persistence by device name + host API; CABLE output, device
  hot-plug, first-run wizard.
- PyTorch is not bundled; a missing runtime shows installation guidance instead
  of crashing.

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
2bcba50dd94a8a61ef484a72bb58798baf16412bf8b2722818569f7a7ea9a55e  FocusMic-Setup-0.1.0.exe
70470a027728523e83d293c8e58d1988d2053da569b4f296c59a1a901a623af6  FocusMic-Runtime-2.9.1-cu128.exe
```

完整说明请见仓库 README；使用前请阅读“已知限制”和“隐私”部分。  
See the repository README for full details, requirements, performance numbers and
privacy notes.
