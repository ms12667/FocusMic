"""Command-line prototype for FocusMic (no browser, no PySide6 required)."""
from __future__ import annotations

import argparse
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from .audio import LiveAudio, SimAudio, list_input_devices
from .paths import PROJECT_ROOT, mediapipe_model
from .pipeline import NativePipeline
from .video import MouthTracker, SimMouth

MEDIAPIPE_MODEL = mediapipe_model("face_landmarker.task")


def cmd_list(args):
    import sounddevice as sd
    print("== 录音设备 ==")
    for d in list_input_devices(sd):
        print(f"  [{d['index']}] {d['name']} | {d['hostapi']} | {d['samplerate']:.0f} Hz")
    if args.list_cameras:
        import cv2
        print("== 摄像头 ==")
        for i in range(6):
            cap = cv2.VideoCapture(i, cv2.CAP_MSMF)
            ok = cap.isOpened()
            if not ok:
                cap.release()
                cap = cv2.VideoCapture(i)
                ok = cap.isOpened()
            if ok:
                print(f"  [{i}] {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x"
                      f"{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))} @ "
                      f"{cap.get(cv2.CAP_PROP_FPS):.0f} fps")
            cap.release()


def main():
    parser = argparse.ArgumentParser(description="FocusMic native CLI")
    parser.add_argument("--list", action="store_true", help="列出录音设备")
    parser.add_argument("--list-cameras", action="store_true", help="同时列出摄像头")
    parser.add_argument("--mic", default=None, help="录音设备索引或名称片段")
    parser.add_argument("--camera", type=int, default=0, help="摄像头索引")
    parser.add_argument("--duration", type=float, default=None, help="运行秒数；默认 Ctrl+C")
    parser.add_argument("--variant", choices=["small", "big"], default="small")
    parser.add_argument("--av-offset-ms", type=float, default=30.0)
    parser.add_argument("--gain-db", type=float, default=6.0)
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    parser.add_argument("--no-output", action="store_true", help="不写 CABLE，只跑模型")
    parser.add_argument("--monitor", action="store_true", help="同时输出到默认耳机/扬声器")
    parser.add_argument("--save-wav", default=None, help="把模型输出保存为 WAV")
    parser.add_argument("--simulate", action="store_true", help="用 testrecordings 回放，不碰设备")
    parser.add_argument("--sim-audio", default=str(PROJECT_ROOT / "testrecordings" / "synth_adj_snr0_mix.wav"))
    parser.add_argument("--sim-mouth", default=str(PROJECT_ROOT / "testrecordings" / "Me-only-clear_mouth25.npy"))
    args = parser.parse_args()

    if args.list:
        cmd_list(args)
        return

    if args.simulate:
        audio = SimAudio(args.sim_audio)
        mouth = SimMouth(args.sim_mouth)
        if args.duration is None:
            args.duration = 20.0
    else:
        audio = LiveAudio(args.mic)
        mouth = MouthTracker(args.camera, model_path=MEDIAPIPE_MODEL)
        print(f"麦克风: [{audio.index}] {audio.info['name']} @ {audio.input_rate} Hz")
        print(f"摄像头: {args.camera} | 模型: {args.variant} | A/V 偏移: {args.av_offset_ms} ms")
        print("按 Ctrl+C 停止。摄像头和麦克风只在本机使用。")

    pipeline = NativePipeline(
        audio, mouth, variant=args.variant, av_offset_ms=args.av_offset_ms,
        gain_db=args.gain_db, output=not args.no_output, monitor=args.monitor,
        save_wav=args.save_wav,
    )
    try:
        pipeline.load(args.device)
        print(f"模型就绪：{args.variant} / {args.device} / hop 0.2 s / window 2 s")
        pipeline.run(duration=args.duration)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
