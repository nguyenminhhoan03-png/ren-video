from __future__ import annotations

import tempfile
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from video_pipeline import ProjectConfig, VideoPipeline, generate_voice_mp3, get_supported_voice_choices


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Video Pipeline — Stock Footage + Narration")
        self.geometry("820x840")
        self.minsize(820, 700)

        self.project_name = tk.StringVar(value="long_form_video")
        self.script_path = tk.StringVar()
        self.voice_path = tk.StringVar()
        self.music_path = tk.StringVar()
        self.output_dir = tk.StringVar(value=r"E:\Project_ItWebDev\Python\ren-video\output")
        self.resolution = tk.StringVar(value="1920x1080")
        self.fps = tk.StringVar(value="30")
        self.auto_generate_voice = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Sẵn sàng")
        self.render_video = tk.BooleanVar(value=True)
        self.tts_voice = tk.StringVar(value="vi-VN-NamMinhNeural")
        self.tts_rate = tk.StringVar(value="-12%")
        self.tts_preview_text = tk.StringVar(
            value="Đây là bản nghe thử để bạn chọn giọng phù hợp cho video của mình."
        )
        self.tts_chunk_size = tk.StringVar(value="240")
        self.tts_workers = tk.StringVar(value="1")
        self.tts_use_cache = tk.BooleanVar(value=False)
        self.tts_profile = tk.StringVar(value="fast")
        self.fast_render = tk.BooleanVar(value=True)
        self.tts_skip_polish = tk.BooleanVar(value=False)  # Polish ON by default

        # --- NEW: Pexels API key & video mode ---
        self.pexels_api_key = tk.StringVar(value="FmIsmwl6a3xuPdRiRlXwzioCXMjkX7PAEUfSJ1CStBPUosglp7rscxny")
        self.use_stock_video = tk.BooleanVar(value=True)

        self._build_ui()

    def _on_frame_configure(self, event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _on_mousewheel(self, event) -> None:
        if self.canvas.winfo_exists():
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _build_ui(self) -> None:
        # Create a scrollable Canvas and a Scrollbar
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        
        main = ttk.Frame(self.canvas, padding=16)
        
        self.canvas_window = self.canvas.create_window((0, 0), window=main, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        main.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        title = ttk.Label(main, text="Video Pipeline — Stock Footage", font=("Segoe UI", 18, "bold"))
        title.pack(anchor="w", pady=(0, 4))

        subtitle = ttk.Label(
            main,
            text="Tạo video với stock footage thật từ Pexels + giọng đọc kể chuyện. Giống phong cách \"Kiến Thức Trước Khi Ngủ\".",
        )
        subtitle.pack(anchor="w", pady=(0, 12))

        form = ttk.Frame(main)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)

        self._row(form, 0, "Project name", self.project_name)
        self._file_row(form, 1, "Script file", self.script_path, ["*.txt", "*.md"])
        self._file_row(form, 2, "Voice file", self.voice_path, ["*.mp3", "*.wav", "*.m4a"], optional=True)
        self._file_row(form, 3, "Music file", self.music_path, ["*.mp3", "*.wav", "*.m4a"], optional=True)
        self._folder_row(form, 4, "Output dir", self.output_dir)
        self._row(form, 5, "Resolution", self.resolution)
        self._row(form, 6, "FPS", self.fps)

        # --- Pexels API Key ---
        ttk.Label(form, text="Pexels API Key").grid(row=7, column=0, sticky="w", pady=5, padx=(0, 8))
        pexels_row = ttk.Frame(form)
        pexels_row.grid(row=7, column=1, sticky="ew", pady=5)
        pexels_row.columnconfigure(0, weight=1)
        self.pexels_entry = ttk.Entry(pexels_row, textvariable=self.pexels_api_key, show="*")
        self.pexels_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(pexels_row, text="Hiện/Ẩn", command=self._toggle_pexels_key).grid(row=0, column=1, padx=(8, 0))
        ttk.Label(pexels_row, text="Đăng ký miễn phí tại pexels.com/api", foreground="gray").grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))

        # --- TTS Settings ---
        ttk.Label(form, text="TTS voice").grid(row=8, column=0, sticky="w", pady=5, padx=(0, 8))
        voice_row = ttk.Frame(form)
        voice_row.grid(row=8, column=1, sticky="ew", pady=5)
        voice_row.columnconfigure(0, weight=3)
        voice_row.columnconfigure(1, weight=1)
        ttk.Combobox(voice_row, textvariable=self.tts_voice, values=get_supported_voice_choices(), state="readonly").grid(row=0, column=0, sticky="ew")
        ttk.Entry(voice_row, textvariable=self.tts_rate, width=10).grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ttk.Label(voice_row, text="Rate (ví dụ -10% cho giọng narrator chậm)").grid(row=1, column=0, sticky="w", pady=(4, 0))

        ttk.Label(form, text="Preview text").grid(row=9, column=0, sticky="nw", pady=5, padx=(0, 8))
        ttk.Entry(form, textvariable=self.tts_preview_text).grid(row=9, column=1, sticky="ew", pady=5)

        ttk.Label(form, text="Chunk size").grid(row=10, column=0, sticky="w", pady=5, padx=(0, 8))
        ttk.Entry(form, textvariable=self.tts_chunk_size, width=10).grid(row=10, column=1, sticky="w", pady=5)

        ttk.Label(form, text="Workers").grid(row=11, column=0, sticky="w", pady=5, padx=(0, 8))
        ttk.Entry(form, textvariable=self.tts_workers, width=10).grid(row=11, column=1, sticky="w", pady=5)

        profile_row = ttk.Frame(form)
        profile_row.grid(row=12, column=1, sticky="w", pady=(0, 6))
        ttk.Checkbutton(profile_row, text="Use cache", variable=self.tts_use_cache).pack(side="left")
        ttk.Label(profile_row, text="Profile").pack(side="left", padx=(12, 6))
        ttk.Combobox(profile_row, textvariable=self.tts_profile, values=["fast", "balanced", "safe"], state="readonly", width=10).pack(side="left")

        preview_actions = ttk.Frame(form)
        preview_actions.grid(row=13, column=1, sticky="w", pady=(2, 6))
        ttk.Button(preview_actions, text="Nghe thử", command=self.preview_voice).pack(side="left")
        ttk.Button(preview_actions, text="Mở thư mục voice tạm", command=self.open_preview_folder).pack(side="left", padx=8)

        # --- Options (Compact Grid) ---
        opts_frame = ttk.Frame(form)
        opts_frame.grid(row=14, column=1, sticky="w", pady=(6, 4))
        
        ttk.Checkbutton(
            opts_frame,
            text="Tự tạo voice từ script",
            variable=self.auto_generate_voice,
        ).grid(row=0, column=0, sticky="w", padx=(0, 12), pady=2)
        
        ttk.Checkbutton(
            opts_frame,
            text="Polish voice (làm ấm giọng)",
            variable=self.tts_skip_polish,
            onvalue=False, offvalue=True,
        ).grid(row=1, column=0, sticky="w", padx=(0, 12), pady=2)
        
        ttk.Checkbutton(
            opts_frame,
            text="Dùng Stock Video từ Pexels",
            variable=self.use_stock_video,
        ).grid(row=2, column=0, sticky="w", padx=(0, 12), pady=2)
        
        ttk.Checkbutton(
            opts_frame,
            text="Fast render (tối ưu tốc độ)",
            variable=self.fast_render,
        ).grid(row=0, column=1, sticky="w", pady=2)
        
        ttk.Checkbutton(
            opts_frame,
            text="Render luôn video có voice",
            variable=self.render_video,
        ).grid(row=1, column=1, sticky="w", pady=2)

        actions = ttk.Frame(main)
        actions.pack(fill="x", pady=16)
        self.run_btn = ttk.Button(actions, text="🎬 Generate Video", command=self.run_pipeline)
        self.run_btn.pack(side="left")

        ttk.Button(actions, text="Open output folder", command=self.open_output_folder).pack(side="left", padx=8)
        ttk.Button(actions, text="Open preview folder", command=self.open_preview_folder).pack(side="left", padx=8)

        self.progress = ttk.Progressbar(main, mode="indeterminate")
        self.progress.pack(fill="x", pady=(4, 10))

        status_box = ttk.LabelFrame(main, text="Status")
        status_box.pack(fill="both", expand=True, padx=0, pady=(0, 4))
        
        scrollbar = ttk.Scrollbar(status_box)
        scrollbar.pack(side="right", fill="y", pady=8, padx=(0, 8))
        
        self.log = tk.Text(status_box, height=8, wrap="word", yscrollcommand=scrollbar.set)
        self.log.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        scrollbar.config(command=self.log.yview)
        self._log_line("GUI đã sẵn sàng.")
        self._log_line("Tip: Đăng ký Pexels API key miễn phí tại pexels.com/api để tải stock video thật.")
        self._log_line("Nếu không có API key, tool sẽ dùng ảnh tĩnh (slide) như trước.")

        ttk.Label(main, textvariable=self.status).pack(anchor="w", pady=(4, 0))

    # ----- helpers -----

    def _toggle_pexels_key(self) -> None:
        current = self.pexels_entry.cget("show")
        self.pexels_entry.config(show="" if current == "*" else "*")

    def _row(self, parent, idx: int, label: str, variable: tk.StringVar) -> None:
        ttk.Label(parent, text=label).grid(row=idx, column=0, sticky="w", pady=5, padx=(0, 8))
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=idx, column=1, sticky="ew", pady=5)

    def _file_row(self, parent, idx: int, label: str, variable: tk.StringVar, patterns, optional: bool = False) -> None:
        ttk.Label(parent, text=label).grid(row=idx, column=0, sticky="w", pady=5, padx=(0, 8))
        row = ttk.Frame(parent)
        row.grid(row=idx, column=1, sticky="ew", pady=5)
        row.columnconfigure(0, weight=1)
        ttk.Entry(row, textvariable=variable).grid(row=0, column=0, sticky="ew")
        ttk.Button(
            row,
            text="Browse",
            command=lambda: self._pick_file(variable, patterns, optional),
        ).grid(row=0, column=1, padx=(8, 0))

    def _folder_row(self, parent, idx: int, label: str, variable: tk.StringVar) -> None:
        ttk.Label(parent, text=label).grid(row=idx, column=0, sticky="w", pady=5, padx=(0, 8))
        row = ttk.Frame(parent)
        row.grid(row=idx, column=1, sticky="ew", pady=5)
        row.columnconfigure(0, weight=1)
        ttk.Entry(row, textvariable=variable).grid(row=0, column=0, sticky="ew")
        ttk.Button(row, text="Browse", command=lambda: self._pick_folder(variable)).grid(row=0, column=1, padx=(8, 0))

    def _pick_file(self, variable: tk.StringVar, patterns, optional: bool = False) -> None:
        path = filedialog.askopenfilename(filetypes=[("Supported files", patterns), ("All files", "*.*")])
        if path:
            variable.set(path)
        elif optional:
            variable.set("")

    def _pick_folder(self, variable: tk.StringVar) -> None:
        path = filedialog.askdirectory()
        if path:
            variable.set(path)

    def _log_line(self, message: str) -> None:
        self.log.insert("end", message + "\n")
        self.log.see("end")

    def set_busy(self, busy: bool) -> None:
        if busy:
            self.progress.start(12)
            self.run_btn.config(state="disabled")
            self.status.set("Đang chạy...")
        else:
            self.progress.stop()
            self.run_btn.config(state="normal")

    def open_output_folder(self) -> None:
        output = Path(self.output_dir.get())
        output.mkdir(parents=True, exist_ok=True)
        import os
        os.startfile(output)

    def _preview_dir(self) -> Path:
        return Path(tempfile.gettempdir()) / "ren_video_tts_preview"

    def open_preview_folder(self) -> None:
        preview_dir = self._preview_dir()
        preview_dir.mkdir(parents=True, exist_ok=True)
        import os
        os.startfile(preview_dir)

    def preview_voice(self) -> None:
        preview_text = self.tts_preview_text.get().strip()
        if not preview_text:
            messagebox.showerror("Missing input", "Nhập text để nghe thử.")
            return

        def worker() -> None:
            try:
                self.after(0, lambda: self.set_busy(True))
                preview_dir = self._preview_dir()
                preview_dir.mkdir(parents=True, exist_ok=True)
                preview_file = preview_dir / "voice_preview.mp3"
                voice = self.tts_voice.get().strip() or "vi-VN-NamMinhNeural"
                rate = self.tts_rate.get().strip() or "-10%"
                chunk_size = int(self.tts_chunk_size.get().strip() or "360")
                workers = int(self.tts_workers.get().strip() or "2")
                use_cache = self.tts_use_cache.get()
                profile = self.tts_profile.get().strip() or "fast"
                do_polish = not self.tts_skip_polish.get()
                if preview_file.exists():
                    preview_file.unlink()
                if profile == "fast":
                    chunk_size = max(chunk_size, 420)
                    workers = max(2, min(workers, 3))
                elif profile == "safe":
                    chunk_size = min(chunk_size, 300)
                    workers = 1
                else:
                    chunk_size = max(320, min(chunk_size, 380))
                    workers = max(2, min(workers, 2))
                self.after(0, lambda: self._log_line(f"Đang tạo file nghe thử bằng {voice} ({rate}), polish={'ON' if do_polish else 'OFF'}..."))
                from video_pipeline import generate_voice_mp3
                preview_script = preview_dir / "preview_script.txt"
                preview_script.write_text(preview_text, encoding="utf-8")
                generate_voice_mp3(
                    preview_script,
                    preview_file,
                    voice,
                    rate=rate,
                    workers=workers,
                    max_chars=chunk_size,
                    use_cache=False,
                    polish=do_polish,
                    allow_fallback_voices=False,
                )
                self.after(0, lambda: self._log_line(f"✓ Đã tạo file nghe thử: {preview_file}"))
                try:
                    import os
                    os.startfile(preview_file)
                except Exception:
                    pass
            except Exception as exc:
                details = traceback.format_exc()
                error_message = str(exc)
                self.after(0, lambda: self._log_line(details))
                self.after(0, lambda msg=error_message: messagebox.showerror("Preview error", msg))
            finally:
                self.after(0, lambda: self.set_busy(False))

        threading.Thread(target=worker, daemon=True).start()

    def run_pipeline(self) -> None:
        if not self.script_path.get().strip():
            messagebox.showerror("Missing input", "Bạn cần chọn script file.")
            return

        def worker() -> None:
            try:
                self.after(0, lambda: self.set_busy(True))
                self.after(0, lambda: self._log_line("=" * 50))
                self.after(0, lambda: self._log_line("Bắt đầu pipeline..."))
                output_dir = Path(self.output_dir.get().strip())
                script_path = Path(self.script_path.get().strip())
                voice_path_text = self.voice_path.get().strip()
                voice_path = Path(voice_path_text) if voice_path_text else output_dir / "voice.mp3"

                # --- Voice generation ---
                if not voice_path_text and self.auto_generate_voice.get():
                    selected_voice = self.tts_voice.get().strip() or "vi-VN-NamMinhNeural"
                    selected_rate = self.tts_rate.get().strip() or "-10%"
                    chunk_size = int(self.tts_chunk_size.get().strip() or "360")
                    workers = int(self.tts_workers.get().strip() or "2")
                    use_cache = self.tts_use_cache.get()
                    do_polish = not self.tts_skip_polish.get()
                    profile = self.tts_profile.get().strip() or "fast"
                    if voice_path.exists():
                        voice_path.unlink()
                    if profile == "fast":
                        chunk_size = max(chunk_size, 420)
                        workers = max(2, min(workers, 3))
                    elif profile == "safe":
                        chunk_size = min(chunk_size, 300)
                        workers = 1
                    else:
                        chunk_size = max(320, min(chunk_size, 380))
                        workers = max(2, min(workers, 2))
                    self.after(0, lambda: self._log_line(
                        f"[1/3] Tạo voice bằng {selected_voice} ({selected_rate}), polish={'ON' if do_polish else 'OFF'}..."
                    ))
                    generate_voice_mp3(
                        script_path,
                        voice_path,
                        selected_voice,
                        rate=selected_rate,
                        workers=workers,
                        max_chars=chunk_size,
                        use_cache=use_cache,
                        polish=do_polish,
                        allow_fallback_voices=True,
                    )
                    self.after(0, lambda: self._log_line(f"✓ Voice đã tạo: {voice_path}"))
                elif not voice_path.exists():
                    raise FileNotFoundError(f"Voice file not found: {voice_path}")

                # --- Pipeline config ---
                pexels_key = self.pexels_api_key.get().strip() if self.use_stock_video.get() else ""
                mode_label = "Stock Video (Pexels)" if pexels_key else "Ảnh tĩnh (fallback)"
                self.after(0, lambda: self._log_line(f"Chế độ hình ảnh: {mode_label}"))

                config = ProjectConfig(
                    project_name=self.project_name.get().strip(),
                    output_dir=output_dir,
                    script_path=script_path,
                    voice_path=voice_path,
                    music_path=Path(self.music_path.get().strip()) if self.music_path.get().strip() else None,
                    resolution=self.resolution.get().strip(),
                    fps=int(self.fps.get().strip()),
                    pexels_api_key=pexels_key,
                )
                pipeline = VideoPipeline(config)
                plan = pipeline.generate_plan()
                chapters = [pipeline.hydrate_chapter(ch) for ch in plan["chapters"]]
                pipeline.export_chapter_markers(chapters)
                pipeline.write_manifest(chapters)

                # --- Generate scene assets ---
                n_scenes = sum(len(ch.scenes or []) for ch in chapters)
                self.after(0, lambda: self._log_line(
                    f"[2/3] Tạo {n_scenes} scene assets ({mode_label})..."
                ))
                slides = pipeline.generate_slides(chapters)
                self.after(0, lambda: self._log_line(f"✓ Đã tạo {len(slides)} scene assets"))

                # --- Render video ---
                if self.render_video.get():
                    self.after(0, lambda: self._log_line("[3/3] Đang render video..."))
                    final_video = pipeline.render_video(chapters, slides, fast_render=self.fast_render.get())
                    self.after(0, lambda: self._log_line(f"✓ Hoàn thành! Video: {final_video}"))
                else:
                    self.after(0, lambda: self._log_line(f"✓ Hoàn thành. Đã tạo {len(slides)} scene assets."))

                self.after(0, lambda: self.status.set("Hoàn thành ✓"))
            except Exception as exc:
                details = traceback.format_exc()
                self.after(0, lambda: self._log_line(details))
                self.after(0, lambda: messagebox.showerror("Pipeline error", str(exc)))
                self.after(0, lambda: self.status.set("Lỗi ✗"))
            finally:
                self.after(0, lambda: self.set_busy(False))

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    App().mainloop()
