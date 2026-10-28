#!/usr/bin/env python3
"""
scripts/record_command_deck.py
--------------------------------------------------------------------------------
全链路自动化实景录制脚本 (Playwright + Chrome)
自动访问 http://localhost:3012/，精准聚焦 Monet 底座 Demo 视口，
点击「启动全链路自动化实景」，全链路执行完成后定格 3.5 秒并保存高清演示视频。

用法:
  python scripts/record_command_deck.py
  python scripts/record_command_deck.py --headless --url http://localhost:3012/
"""

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_URL = "http://127.0.0.1:3012/"
DEFAULT_OUTPUT = str(REPO_ROOT / "landing/public/demos/command-deck-pipeline.webm")
VIEWPORT_WIDTH = 1360
VIEWPORT_HEIGHT = 740
DEVICE_SCALE_FACTOR = 2  # Retina 2x 高清文字渲染


def log(msg: str):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [RecordDemo] {msg}", flush=True)


def parse_args():
    parser = argparse.ArgumentParser(description="Record JobHunter Command Deck Automation Demo")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"Target URL (default: {DEFAULT_URL})")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help=f"Output video path (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--headless", action="store_true", default=False, help="Run headless mode (default: False)")
    parser.add_argument("--post-delay", type=float, default=3.5, help="Seconds to freeze final frame (default: 3.5)")
    parser.add_argument("--timeout", type=int, default=300, help="Max recording timeout in seconds (default: 300)")
    parser.add_argument("--width", type=int, default=VIEWPORT_WIDTH, help="Recording viewport width")
    parser.add_argument("--height", type=int, default=VIEWPORT_HEIGHT, help="Recording viewport height")
    return parser.parse_args()


def record_demo(args):
    output_path = Path(args.output).resolve()
    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    temp_video_dir = output_dir / "_temp_recording"
    if temp_video_dir.exists():
        shutil.rmtree(temp_video_dir)
    temp_video_dir.mkdir(parents=True, exist_ok=True)

    log(f"Starting browser recording (Headless: {args.headless})...")
    log(f"Target URL: {args.url}")
    log(f"Viewport: {args.width}x{args.height} (DPR: {DEVICE_SCALE_FACTOR})")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=args.headless,
                channel="chrome",
                args=["--disable-blink-features=AutomationControlled"]
            )

            context = browser.new_context(
                viewport={"width": args.width, "height": args.height},
                device_scale_factor=DEVICE_SCALE_FACTOR,
                record_video_dir=str(temp_video_dir),
                record_video_size={"width": args.width, "height": args.height}
            )

            page = context.new_page()

            log(f"Navigating to {args.url} ...")
            page.goto(args.url, wait_until="commit", timeout=60000)

            log("Waiting for Command Deck canvas (#command-deck-canvas)...")
            page.wait_for_selector("#command-deck-canvas", timeout=30000)

            log("Waiting for load state and hydration...")
            page.wait_for_load_state("load")
            time.sleep(2.0)

            # 隐藏顶部导航并调整滚动位置，使画布与视口 1:1 紧凑对齐（去除上下多余外边距）
            page.add_style_tag(content="header { display: none !important; }")
            page.evaluate("""() => {
                const canvas = document.getElementById('command-deck-canvas');
                if (canvas) {
                    const rect = canvas.getBoundingClientRect();
                    const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
                    // 让画布顶部留 10px 边距，完美居中
                    window.scrollTo({
                        top: rect.top + scrollTop - 10,
                        behavior: 'instant'
                    });
                }
            }""")

            time.sleep(1.0)

            # 若侧栏处于收起态，则先点击展开按钮
            expand_btn = page.locator("button[title='展开链路面板']")
            if expand_btn.is_visible():
                log("Sidebar is collapsed, expanding...")
                expand_btn.click()
                time.sleep(0.5)

            # 寻找启动按钮并点击
            log("Locating '启动全链路自动化实景' button...")
            start_btn = page.locator("#btn-start-auto-pipeline")
            if not start_btn.is_visible():
                start_btn = page.locator("button:has-text('启动全链路自动化实景')").first
                if not start_btn.is_visible():
                    start_btn.scroll_into_view_if_needed()

            log("Triggering '启动全链路自动化实景'...")
            start_btn.click()

            # 等待流水线启动（data-pipeline-active 变为 'true'）
            log("Waiting for pipeline to begin...")
            try:
                page.wait_for_selector(
                    "#command-deck-canvas[data-pipeline-active='true']",
                    timeout=8000
                )
                log("Pipeline started successfully!")
            except Exception:
                log("Fallback: calling DOM button click directly...")
                page.evaluate("""() => {
                    const btn = document.getElementById('btn-start-auto-pipeline') || 
                                Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('启动全链路自动化实景'));
                    if (btn) btn.click();
                }""")
                try:
                    page.wait_for_selector(
                        "#command-deck-canvas[data-pipeline-active='true']",
                        timeout=8000
                    )
                    log("Pipeline started successfully via fallback!")
                except Exception:
                    log("Notice: pipeline active marker not caught, proceeding to monitor flow...")

            # 监听流程流转，打印各个阶段
            last_step = None
            had_deliver_stage = False
            deliver_start_time = None
            start_time = time.time()

            log("Monitoring full automation pipeline...")
            while True:
                elapsed = time.time() - start_time
                if elapsed > args.timeout:
                    log(f"WARNING: Reached maximum timeout ({args.timeout}s). Ending recording.")
                    break

                state = page.evaluate("""() => {
                    const canvas = document.getElementById('command-deck-canvas');
                    if (!canvas) return { step: null, active: 'false', delivering: 'false' };
                    return {
                        step: canvas.getAttribute('data-pipeline-step'),
                        active: canvas.getAttribute('data-pipeline-active') || 'false',
                        delivering: canvas.getAttribute('data-is-delivering') || 'false'
                    };
                }""")
                current_step = state.get("step")
                is_active = state.get("active")
                is_delivering = state.get("delivering")

                if current_step and current_step != last_step:
                    log(f"Stage transition: [{current_step}] (elapsed: {elapsed:.1f}s)")
                    last_step = current_step

                if current_step == "deliver":
                    if not deliver_start_time:
                        deliver_start_time = time.time()
                    had_deliver_stage = True

                # 判定结束条件：曾经进入过 deliver 步骤，且交付动画已充分执行（至少 8s），且现在已转入 idle/非 active 且非投递中
                if had_deliver_stage and deliver_start_time and (time.time() - deliver_start_time >= 8.0):
                    if current_step == "idle" or (is_active == "false" and is_delivering == "false"):
                        log(f"Pipeline finished! Final stage 'deliver' completed (Total elapsed: {elapsed:.1f}s)")
                        break

                time.sleep(0.5)

            # 终章留白：在图 2 定格状态静止保持
            log(f"Freezing final completion frame for {args.post_delay}s...")
            time.sleep(args.post_delay)

            # 保存并获取视频路径 (使用 Playwright 官方原生 save_as)
            video_handle = page.video
            page.close()
            if output_path.exists():
                output_path.unlink()
            video_handle.save_as(str(output_path))
            context.close()
            browser.close()
    finally:
        # 始终清理临时录制碎片目录
        if temp_video_dir.exists():
            shutil.rmtree(temp_video_dir)

    log(f"SUCCESS: Demo video saved to: {output_path}")

    file_size_mb = output_path.stat().st_size / (1024 * 1024)
    log(f"Video file size: {file_size_mb:.2f} MB")

    # 检查系统中是否有 ffmpeg，如果有则自动转码一份 mp4
    system_ffmpeg = shutil.which("ffmpeg")
    if not system_ffmpeg:
        # 尝试检查 Homebrew 或 Playwright 缓存
        brew_ffmpeg = Path("/opt/homebrew/bin/ffmpeg")
        if brew_ffmpeg.exists():
            system_ffmpeg = str(brew_ffmpeg)

    if system_ffmpeg:
        mp4_path = output_path.with_suffix(".mp4")
        log(f"Detected ffmpeg ({system_ffmpeg}), converting to MP4: {mp4_path} ...")
        cmd = [
            system_ffmpeg, "-y",
            "-i", str(output_path),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            "-crf", "22",
            str(mp4_path)
        ]
        ret = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if ret.returncode == 0 and mp4_path.exists():
            mp4_size_mb = mp4_path.stat().st_size / (1024 * 1024)
            log(f"SUCCESS: MP4 video generated at: {mp4_path} ({mp4_size_mb:.2f} MB)")
        else:
            log(f"Notice: MP4 conversion skipped or failed: {ret.stderr.decode('utf-8', errors='ignore')[:200]}")
    else:
        log("Notice: ffmpeg not in PATH. WebM video is ready for modern browsers and GitHub uploads.")

    return output_path


if __name__ == "__main__":
    args = parse_args()
    try:
        record_demo(args)
    except KeyboardInterrupt:
        log("Recording aborted by user.")
        sys.exit(1)
