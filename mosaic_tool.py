import queue
import threading
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk
from tkinter import ttk

import imageio_ffmpeg
from PIL import Image, ImageEnhance, ImageTk


APP_NAME = "通通变成马赛克"
ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = ROOT / "mosaic_outputs"


class MosaicTool:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("760x780")
        self.root.minsize(680, 680)

        self.video_path = tk.StringVar()
        self.size_var = tk.IntVar(value=480)
        self.block_var = tk.IntVar(value=8)
        self.fps_var = tk.IntVar(value=24)
        self.count_var = tk.IntVar(value=240)
        self.status_var = tk.StringVar(value="选择视频后开始处理")

        self.msg_queue = queue.Queue()
        self.processing = False
        self.paused = False
        self.preview_index = 0
        self.preview_after_id = None
        self.output_dir = None
        self.source_dir = None
        self.mosaic_dir = None
        self.preview_photos = []
        self.preview_paths = []
        self.current_preview_image = None

        self.build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self.drain_queue)

    def build_ui(self):
        outer = ttk.Frame(self.root, padding=(16, 14, 16, 12))
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x")
        title = ttk.Label(header, text=APP_NAME, style="Title.TLabel")
        title.pack(side="left")
        ttk.Button(header, text="新手指南", command=self.show_guide).pack(side="left", padx=(10, 0))

        subtitle = ttk.Label(outer, text="把视频变成干净的像素块动画", style="Muted.TLabel")
        subtitle.pack(anchor="w", pady=(2, 12))

        video_box = ttk.LabelFrame(outer, text="视频")
        video_box.pack(fill="x", pady=(0, 10))
        pick_row = ttk.Frame(video_box, padding=(10, 8))
        pick_row.pack(fill="x")
        ttk.Entry(pick_row, textvariable=self.video_path).pack(side="left", fill="x", expand=True)
        ttk.Button(pick_row, text="选择视频", command=self.pick_video).pack(side="left", padx=(8, 0))

        settings = ttk.LabelFrame(outer, text="参数")
        settings.pack(fill="x", pady=(0, 10))
        self.add_spin(settings, "尺寸", self.size_var, 240, 900, 20, 0)
        self.add_spin(settings, "马赛克块", self.block_var, 3, 40, 1, 1)
        self.add_spin(settings, "GIF FPS", self.fps_var, 8, 40, 1, 2)
        self.add_spin(settings, "提取帧数", self.count_var, 30, 500, 10, 3)

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(0, 10))
        self.process_btn = ttk.Button(actions, text="开始处理", command=self.start_processing, style="Accent.TButton")
        self.process_btn.pack(side="left")
        self.pause_btn = ttk.Button(actions, text="暂停预览", command=self.toggle_preview, state="disabled")
        self.pause_btn.pack(side="left", padx=(8, 0))
        self.gif_btn = ttk.Button(actions, text="导出 GIF", command=self.export_gif, state="disabled")
        self.gif_btn.pack(side="left", padx=(8, 0))
        self.png_btn = ttk.Button(actions, text="导出 PNG 截图", command=self.export_png, state="disabled")
        self.png_btn.pack(side="left", padx=(8, 0))

        preview_box = ttk.LabelFrame(outer, text="预览")
        preview_box.pack(fill="both", expand=True)
        preview_surface = tk.Frame(preview_box, bg="#f4f5f7", highlightthickness=1, highlightbackground="#d8dde3")
        preview_surface.pack(fill="both", expand=True, padx=8, pady=8)
        self.preview_label = tk.Label(preview_surface, anchor="center", bg="#f4f5f7")
        self.preview_label.pack(fill="both", expand=True)

        self.progress = ttk.Progressbar(outer, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(10, 5))
        ttk.Label(outer, textvariable=self.status_var, style="Muted.TLabel").pack(anchor="w")

    def add_spin(self, parent, label, var, low, high, step, col):
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=col, sticky="ew", padx=10, pady=9)
        ttk.Label(frame, text=label, style="FieldName.TLabel").pack(anchor="w")
        ttk.Spinbox(frame, from_=low, to=high, increment=step, textvariable=var, width=8).pack(anchor="w")
        parent.columnconfigure(col, weight=1)

    def show_guide(self):
        guide = tk.Toplevel(self.root)
        guide.title("新手指南")
        guide.resizable(False, False)
        guide.transient(self.root)
        guide.grab_set()

        body = ttk.Frame(guide, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="新手指南", style="DialogTitle.TLabel").pack(anchor="w")
        ttk.Label(
            body,
            text=(
                "1. 点“选择视频”，优先选 MP4。\n"
                "2. 第一次推荐：尺寸 480，马赛克块 8，GIF FPS 24，提取帧数 240。\n"
                "3. 点“开始处理”，等进度条完成后会自动预览。\n"
                "4. 点“导出 GIF”保存动图。\n"
                "5. 点“导出 PNG 截图”保存当前画面。\n"
                "6. 如果卡，把尺寸和提取帧数调低。"
            ),
            justify="left",
            wraplength=380,
            style="Guide.TLabel",
        ).pack(anchor="w", pady=(12, 16))
        ttk.Button(body, text="知道了", command=guide.destroy).pack(anchor="e")
        guide.update_idletasks()
        width = max(430, guide.winfo_reqwidth())
        height = guide.winfo_reqheight()
        x = self.root.winfo_x() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_y() + max(0, (self.root.winfo_height() - height) // 2)
        guide.geometry(f"{width}x{height}+{x}+{y}")

    def pick_video(self):
        path = filedialog.askopenfilename(
            title="选择视频",
            filetypes=[("Video files", "*.mp4 *.mov *.m4v *.webm"), ("All files", "*.*")],
        )
        if path:
            self.video_path.set(path)

    def start_processing(self):
        if self.processing:
            return
        video = Path(self.video_path.get().strip())
        if not video.exists():
            messagebox.showerror(APP_NAME, "先选择一个可用的视频文件。")
            return
        if not Path(imageio_ffmpeg.get_ffmpeg_exe()).exists():
            messagebox.showerror(APP_NAME, "找不到 ffmpeg 视频处理组件。")
            return

        self.stop_preview()
        self.preview_photos = []
        self.preview_paths = []
        self.current_preview_image = None
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_stem = "".join(ch if ch.isalnum() else "_" for ch in video.stem)[:40] or "video"
        self.output_dir = OUTPUT_ROOT / f"{safe_stem}_{stamp}"
        self.source_dir = self.output_dir / "source_frames"
        self.mosaic_dir = self.output_dir / "mosaic_frames"
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.mosaic_dir.mkdir(parents=True, exist_ok=True)

        self.processing = True
        self.process_btn.configure(state="disabled")
        self.gif_btn.configure(state="disabled")
        self.png_btn.configure(state="disabled")
        self.pause_btn.configure(state="disabled")
        self.progress.configure(value=0)
        self.status_var.set("正在处理...")

        thread = threading.Thread(target=self.process_video, args=(video,), daemon=True)
        thread.start()

    def process_video(self, video):
        try:
            frame_count = max(2, int(self.count_var.get()))
            self.queue_status("提取视频帧...", 5)
            self.extract_video_frames(video, frame_count)
            self.queue_status("生成马赛克帧...", 55)
            self.make_mosaic_frames(frame_count)
            self.msg_queue.put(("done", None))
        except Exception as exc:
            self.msg_queue.put(("error", str(exc)))

    def extract_video_frames(self, video, frame_count):
        meta_reader = imageio_ffmpeg.read_frames(str(video))
        try:
            meta = next(meta_reader)
        finally:
            meta_reader.close()

        duration = float(meta.get("duration") or 0)
        if duration <= 0:
            raise RuntimeError("无法识别视频时长，请换一个普通 MP4 视频再试。")

        extract_fps = max(0.1, frame_count / duration)
        reader = imageio_ffmpeg.read_frames(
            str(video),
            output_params=["-vf", f"fps={extract_fps:.6f}", "-frames:v", str(frame_count)],
        )
        try:
            frame_meta = next(reader)
            width, height = frame_meta["size"]
            saved = 0
            for saved, frame in enumerate(reader, start=1):
                image = Image.frombytes("RGB", (width, height), frame)
                image.save(self.source_dir / f"frame_{saved - 1:04d}.png")
                if saved % 10 == 0 or saved == frame_count:
                    percent = 5 + int(saved / frame_count * 45)
                    self.queue_status(f"提取视频帧 {saved}/{frame_count}", percent)
                if saved >= frame_count:
                    break
        finally:
            reader.close()

        if saved == 0:
            raise RuntimeError("视频提帧失败，没有生成任何画面。")

    def make_mosaic_frames(self, frame_count):
        size = max(120, int(self.size_var.get()))
        block = max(2, int(self.block_var.get()))
        small_size = max(8, size // block)
        source_paths = sorted(self.source_dir.glob("*.png"))
        total = len(source_paths)
        if total == 0:
            raise RuntimeError("没有生成视频帧。")

        for index, path in enumerate(source_paths):
            image = Image.open(path).convert("RGB")
            image = image.resize((small_size, small_size), Image.Resampling.BILINEAR)
            image = ImageEnhance.Color(image).enhance(1.05)
            image = ImageEnhance.Contrast(image).enhance(1.05)
            image = image.resize((size, size), Image.Resampling.NEAREST)
            image.save(self.mosaic_dir / f"mosaic_{index:04d}.png")
            if (index + 1) % 20 == 0 or index + 1 == total:
                percent = 55 + int((index + 1) / total * 25)
                self.queue_status(f"生成马赛克帧 {index + 1}/{total}", percent)

    def prepare_preview(self):
        paths = sorted(self.mosaic_dir.glob("*.png"))
        total = len(paths)
        if total == 0:
            raise RuntimeError("没有生成马赛克预览帧。")

        self.preview_photos = []
        self.preview_paths = []
        for index, path in enumerate(paths):
            image = Image.open(path).convert("RGB")
            self.preview_photos.append(ImageTk.PhotoImage(image))
            self.preview_paths.append(path)
            if (index + 1) % 50 == 0 or index + 1 == total:
                percent = 85 + int((index + 1) / total * 10)
                self.status_var.set(f"准备预览 {index + 1}/{total}")
                self.progress.configure(value=percent)
                self.root.update_idletasks()

    def export_gif(self):
        if not self.preview_paths:
            return
        out = filedialog.asksaveasfilename(
            title="导出 GIF",
            defaultextension=".gif",
            initialfile="mosaic.gif",
            filetypes=[("GIF", "*.gif")],
        )
        if not out:
            return
        try:
            fps = max(1, min(40, int(self.fps_var.get())))
            duration_ms = round(1000 / fps)
            frames = [
                Image.open(path).convert("P", palette=Image.Palette.ADAPTIVE, colors=128)
                for path in self.preview_paths
            ]
            frames[0].save(
                out,
                save_all=True,
                append_images=frames[1:],
                duration=duration_ms,
                loop=0,
                optimize=False,
                disposal=2,
            )
            self.status_var.set(f"GIF 已导出：{out}")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"导出 GIF 失败：\n{exc}")

    def export_png(self):
        if not self.preview_paths:
            return
        out = filedialog.asksaveasfilename(
            title="导出 PNG 截图",
            defaultextension=".png",
            initialfile="mosaic_preview.png",
            filetypes=[("PNG", "*.png")],
        )
        if not out:
            return
        try:
            index = self.preview_index % len(self.preview_paths)
            Image.open(self.preview_paths[index]).save(out)
            self.status_var.set(f"PNG 截图已导出：{out}")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"导出 PNG 失败：\n{exc}")

    def toggle_preview(self):
        self.paused = not self.paused
        self.pause_btn.configure(text="继续预览" if self.paused else "暂停预览")

    def start_preview(self):
        self.paused = False
        self.pause_btn.configure(state="normal", text="暂停预览")
        self.gif_btn.configure(state="normal")
        self.png_btn.configure(state="normal")
        self.preview_index = -1
        self.animate()

    def animate(self):
        if self.preview_photos and not self.paused:
            self.preview_index = (self.preview_index + 1) % len(self.preview_photos)
            photo = self.preview_photos[self.preview_index]
            self.preview_label.configure(image=photo)
            self.current_preview_image = photo
        delay = max(1, round(1000 / max(1, int(self.fps_var.get()))))
        self.preview_after_id = self.root.after(delay, self.animate)

    def stop_preview(self):
        if self.preview_after_id:
            self.root.after_cancel(self.preview_after_id)
            self.preview_after_id = None

    def queue_status(self, text, progress):
        self.msg_queue.put(("status", text, max(0, min(100, progress))))

    def drain_queue(self):
        try:
            while True:
                item = self.msg_queue.get_nowait()
                kind = item[0]
                if kind == "status":
                    self.status_var.set(item[1])
                    self.progress.configure(value=item[2])
                elif kind == "done":
                    try:
                        self.status_var.set("准备预览...")
                        self.progress.configure(value=85)
                        self.prepare_preview()
                        self.processing = False
                        self.process_btn.configure(state="normal")
                        self.progress.configure(value=100)
                        self.status_var.set(f"处理完成。输出目录：{self.output_dir}")
                        self.start_preview()
                    except Exception as exc:
                        self.processing = False
                        self.process_btn.configure(state="normal")
                        self.progress.configure(value=0)
                        self.status_var.set("处理失败")
                        messagebox.showerror(APP_NAME, str(exc))
                elif kind == "error":
                    self.processing = False
                    self.process_btn.configure(state="normal")
                    self.progress.configure(value=0)
                    self.status_var.set("处理失败")
                    messagebox.showerror(APP_NAME, item[1])
        except queue.Empty:
            pass
        self.root.after(100, self.drain_queue)

    def close(self):
        self.stop_preview()
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 19, "bold"))
        style.configure("DialogTitle.TLabel", font=("Microsoft YaHei UI", 15, "bold"))
        style.configure("Muted.TLabel", foreground="#5f6368")
        style.configure("FieldName.TLabel", foreground="#333333")
        style.configure("Guide.TLabel", font=("Microsoft YaHei UI", 10), foreground="#202124")
        style.configure("Accent.TButton", font=("Microsoft YaHei UI", 10, "bold"))
    except tk.TclError:
        pass
    MosaicTool(root)
    root.mainloop()


if __name__ == "__main__":
    main()
