from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

import requests

from PIL import Image, ImageDraw, ImageFilter, ImageFont


# ---------------------------------------------------------------------------
# Vietnamese → English keyword dictionary for stock video search
# ---------------------------------------------------------------------------

VI_EN_KEYWORDS: dict[str, str] = {
    # Space / Astronomy
    "vũ trụ": "universe cosmos",
    "thiên hà": "galaxy",
    "hành tinh": "planet",
    "ngôi sao": "star",
    "sao": "star",
    "mặt trời": "sun solar",
    "mặt trăng": "moon lunar",
    "trái đất": "earth planet",
    "hố đen": "black hole",
    "siêu tân tinh": "supernova explosion",
    "big bang": "big bang universe origin",
    "không gian": "outer space",
    "tàu vũ trụ": "spaceship spacecraft",
    "phi hành gia": "astronaut",
    "dải ngân hà": "milky way galaxy",
    "sao neutron": "neutron star",
    "magnetar": "magnetar magnetic star",
    "bức xạ": "radiation",
    "ánh sáng": "light rays beam",
    "quỹ đạo": "orbit",
    "hệ mặt trời": "solar system",
    "sao hỏa": "mars planet",
    "sao mộc": "jupiter planet",
    "tinh vân": "nebula",
    "vật chất tối": "dark matter universe",
    "năng lượng tối": "dark energy",
    "đa vũ trụ": "multiverse parallel",
    "chân trời sự kiện": "event horizon black hole",
    "plasma": "plasma energy",

    # Nature / Geography
    "đại dương": "ocean sea waves",
    "biển": "ocean sea",
    "núi": "mountain landscape",
    "rừng": "forest trees",
    "sa mạc": "desert sand dunes",
    "sông": "river water",
    "thác nước": "waterfall nature",
    "bầu trời": "sky clouds",
    "mưa": "rain weather",
    "bão": "storm thunder",
    "tuyết": "snow winter",
    "núi lửa": "volcano eruption",
    "động đất": "earthquake disaster",

    # History / Civilization
    "cổ đại": "ancient civilization",
    "kim tự tháp": "pyramid egypt ancient",
    "đế chế": "empire kingdom ancient",
    "nền văn minh": "civilization ancient",
    "chiến tranh": "war battle",
    "di tích": "ruins ancient archaeological",
    "đền": "temple ancient",
    "lịch sử": "history historical",
    "thần thoại": "mythology gods",

    # Science / Technology
    "khoa học": "science research",
    "công nghệ": "technology futuristic",
    "robot": "robot artificial intelligence",
    "dna": "dna genetics biology",
    "tế bào": "cell biology microscope",
    "nguyên tử": "atom particle physics",
    "vật lý": "physics science",
    "einstein": "einstein relativity physics",
    "thời gian": "time clock abstract",
    "du hành thời gian": "time travel wormhole",

    # Human / Emotion
    "con người": "human people",
    "nhân loại": "humanity civilization",
    "tương lai": "future technology city",
    "sự sống": "life nature",
    "cái chết": "death darkness",
    "bóng tối": "darkness shadow",
    "ánh sáng": "light bright rays",
    "im lặng": "silence calm quiet",
}

# Topic fallback keywords for Pexels search
TOPIC_SEARCH_FALLBACK: dict[str, str] = {
    "space": "space galaxy universe stars nebula",
    "history": "ancient ruins temple civilization",
    "future": "futuristic city technology neon",
    "ocean": "ocean deep sea underwater waves",
    "war": "war battlefield soldiers",
    "documentary": "cinematic nature landscape aerial",
}


@dataclass
class Scene:
    title: str
    start_sec: float
    end_sec: float
    text: str
    prompt: str
    is_key_scene: bool = False
    image_path: Optional[str] = None
    clip_path: Optional[str] = None


@dataclass
class Chapter:
    title: str
    start_sec: float
    end_sec: float
    script: str
    image_prompt: str
    scenes: Optional[List[Scene]] = None
    image_path: Optional[str] = None
    clip_path: Optional[str] = None


@dataclass
class ProjectConfig:
    project_name: str
    output_dir: Path
    script_path: Path
    voice_path: Path
    music_path: Optional[Path] = None
    resolution: str = "1920x1080"
    fps: int = 30
    chapter_seconds: int = 60
    pexels_api_key: str = ""


class VideoPipeline:
    def __init__(self, config: ProjectConfig):
        self.config = config
        self.output_dir = config.output_dir
        self.assets_dir = self.output_dir / "assets"
        self.chapters_dir = self.output_dir / "chapters"
        self.render_dir = self.output_dir / "render"
        self.videos_dir = self.output_dir / "stock_videos"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.chapters_dir.mkdir(parents=True, exist_ok=True)
        self.render_dir.mkdir(parents=True, exist_ok=True)
        self.videos_dir.mkdir(parents=True, exist_ok=True)

    # ----- hydration helpers -----

    def hydrate_scene(self, scene: Scene | dict) -> Scene:
        if isinstance(scene, Scene):
            return scene
        return Scene(**scene)

    def hydrate_chapter(self, chapter: Chapter | dict) -> Chapter:
        if isinstance(chapter, Chapter):
            return chapter
        data = dict(chapter)
        data["scenes"] = [self.hydrate_scene(s) for s in data.get("scenes", [])] if data.get("scenes") else None
        return Chapter(**data)

    # ----- script loading / splitting -----

    def load_script(self) -> str:
        return self.config.script_path.read_text(encoding="utf-8")

    def split_into_chapters(self, script: str) -> List[Chapter]:
        script = self.normalize_script(script)
        parts = [p.strip() for p in script.split("\n\n") if p.strip()]
        if not parts:
            parts = [script.strip()]
        if len(parts) == 1 and len(parts[0].split()) > 120:
            words = parts[0].split()
            third = max(1, len(words) // 3)
            parts = [" ".join(words[:third]), " ".join(words[third:third * 2]), " ".join(words[third * 2:])]

        chapters: List[Chapter] = []
        cursor = 0.0
        for index, part in enumerate(parts, start=1):
            est_duration = max(20.0, len(part.split()) / 2.3)
            scenes = self.split_into_scenes(part, cursor, est_duration)
            chapter = Chapter(
                title=f"Chapter {index}",
                start_sec=cursor,
                end_sec=cursor + est_duration,
                script=part,
                image_prompt=self.build_image_prompt(part),
                scenes=scenes,
            )
            chapters.append(chapter)
            cursor += est_duration
        return chapters

    def split_into_scenes(self, text: str, chapter_start: float, chapter_duration: float) -> List[Scene]:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        if len(sentences) <= 1:
            sentences = [s.strip() for s in re.split(r"[,;:\n]+", text) if s.strip()] or [text.strip()]

        if len(sentences) == 1 and len(sentences[0].split()) > 18:
            words = sentences[0].split()
            midpoint = max(1, len(words) // 2)
            sentences = [" ".join(words[:midpoint]), " ".join(words[midpoint:])]

        # Target a dynamic scene change every ~7 seconds
        target_scene_duration = 7.0
        scene_count = max(3, math.ceil(chapter_duration / target_scene_duration))
        scene_count = min(len(sentences), scene_count)
        scene_count = max(2, scene_count)  # At least 2 scenes per chapter
        
        chunk_size = max(1, math.ceil(len(sentences) / scene_count))
        chunks = [sentences[i:i + chunk_size] for i in range(0, len(sentences), chunk_size)]
        if len(chunks) == 1 and len(sentences) > 1:
            mid = max(1, len(sentences) // 2)
            chunks = [sentences[:mid], sentences[mid:]]
        scene_duration = chapter_duration / max(1, len(chunks))

        scenes: List[Scene] = []
        total_scenes = len(chunks)
        for i, chunk in enumerate(chunks, start=1):
            text_block = " ".join(chunk)
            start = chapter_start + (i - 1) * scene_duration
            end = start + scene_duration
            scenes.append(Scene(
                title=f"Scene {i}",
                start_sec=start,
                end_sec=end,
                text=text_block,
                prompt=self.build_scene_prompt(text_block),
                is_key_scene=self.is_key_scene(text_block, i, total_scenes),
            ))
        return scenes

    def normalize_script(self, text: str) -> str:
        text = text.replace("\r\n", "\n")
        text = re.sub(r"^[\-•*\d\.\)\s]+", "", text, flags=re.M)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        return text.strip()

    # ----- keyword / prompt helpers -----

    def extract_keywords(self, text: str, limit: int = 6) -> List[str]:
        words = re.findall(r"[\wÀ-ỹ]+", text.lower())
        stopwords = {
            "và", "là", "của", "cho", "một", "những", "các", "được", "trong", "khi", "đó", "này",
            "the", "and", "for", "with", "from", "that", "this", "are", "was", "were", "to", "of",
            "không", "có", "đến", "như", "bạn", "nếu", "còn", "mọi", "chỉ", "rồi",
            "nhưng", "thì", "hay", "hoặc", "vì", "nên", "đã", "sẽ", "đang", "bởi",
        }
        freq: dict[str, int] = {}
        for word in words:
            if len(word) < 3 or word in stopwords:
                continue
            freq[word] = freq.get(word, 0) + 1
        ranked = sorted(freq.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))
        return [word for word, _ in ranked[:limit]]

    def translate_keywords_to_english(self, text: str) -> str:
        """Translate Vietnamese keywords to English for stock video search."""
        text_lower = text.lower()
        matched_en: list[str] = []

        # Try matching multi-word phrases first (longer matches first)
        sorted_keys = sorted(VI_EN_KEYWORDS.keys(), key=len, reverse=True)
        for vi_phrase in sorted_keys:
            if vi_phrase in text_lower:
                matched_en.append(VI_EN_KEYWORDS[vi_phrase])

        if matched_en:
            # Deduplicate while preserving order
            seen: set[str] = set()
            result: list[str] = []
            for phrase in matched_en:
                for word in phrase.split():
                    if word not in seen:
                        seen.add(word)
                        result.append(word)
            return " ".join(result[:8])

        # Fallback: use topic detection
        topic = self.scene_topic(text)
        return TOPIC_SEARCH_FALLBACK.get(topic, "cinematic nature landscape")

    def build_scene_prompt(self, text: str) -> str:
        topic = self.scene_topic(text)
        keywords = self.extract_keywords(text, limit=5)
        cleaned = " ".join(text.split())[:220]
        keyword_text = ", ".join(keywords)
        return (
            f"{topic} cinematic documentary scene, realistic details, moody lighting, high quality composition, "
            f"visual focus on: {keyword_text}. Context: {cleaned}"
        )

    def build_video_search_query(self, text: str) -> str:
        """Build an English search query for Pexels video API."""
        return self.translate_keywords_to_english(text)

    def score_scene_importance(self, text: str, scene_index: int, total_scenes: int) -> float:
        t = text.lower()
        score = 0.0
        importance_words = ["why", "vì sao", "câu hỏi", "sự thật", "bí ẩn", "quan trọng", "then chốt", "khủng khiếp", "đột phá", "khám phá"]
        emotional_words = ["nguy hiểm", "tương lai", "sụp đổ", "mất", "chết", "vĩ đại", "cuối cùng", "đầu tiên"]
        if any(w in t for w in importance_words):
            score += 0.35
        if any(w in t for w in emotional_words):
            score += 0.25
        if scene_index == 1:
            score += 0.2
        if scene_index == total_scenes:
            score += 0.15
        if len(text.split()) > 28:
            score += 0.15
        return min(score, 1.0)

    def is_key_scene(self, text: str, scene_index: int, total_scenes: int) -> bool:
        return self.score_scene_importance(text, scene_index, total_scenes) >= 0.45

    def scene_topic(self, text: str) -> str:
        t = text.lower()
        topics = {
            "space": ["vũ trụ", "hành tinh", "không gian", "sao", "thiên hà", "trái đất", "mặt trăng"],
            "history": ["cổ đại", "kim tự tháp", "ai cập", "đền", "đế chế", "thần thoại", "di tích"],
            "future": ["tương lai", "robot", "ai", "tàu", "trạm", "neon", "thành phố"],
            "ocean": ["biển", "đại dương", "sóng", "nước", "tàu ngầm"],
            "war": ["chiến tranh", "trận", "quân", "binh", "xâm lược"],
        }
        for topic, words in topics.items():
            if any(w in t for w in words):
                return topic
        return "documentary"

    # ----- Pexels Video API -----

    def fetch_pexels_video(
        self,
        query: str,
        output_path: Path,
        min_duration: float = 5.0,
        target_duration: float = 30.0,
        page: int = 1,
    ) -> bool:
        """Search and download a stock video from Pexels API."""
        api_key = self.config.pexels_api_key
        if not api_key:
            return False

        headers = {"Authorization": api_key}
        params = {
            "query": query,
            "per_page": 15,
            "page": page,
            "orientation": "landscape",
        }

        try:
            resp = requests.get(
                "https://api.pexels.com/videos/search",
                headers=headers,
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return False

        videos = data.get("videos", [])
        if not videos:
            return False

        # Filter videos: prefer ones with duration >= min_duration
        candidates = [v for v in videos if v.get("duration", 0) >= min_duration]
        if not candidates:
            candidates = videos

        # Sort by how close duration is to target, prefer longer
        candidates.sort(key=lambda v: abs(v.get("duration", 0) - target_duration))

        for video in candidates[:5]:
            video_files = video.get("video_files", [])
            if not video_files:
                continue

            # Prefer HD (1920x1080) or close to it
            hd_files = [
                f for f in video_files
                if f.get("width", 0) >= 1280
                and f.get("quality") in ("hd", "sd")
                and f.get("file_type") == "video/mp4"
            ]
            if not hd_files:
                hd_files = [f for f in video_files if f.get("file_type") == "video/mp4"]
            if not hd_files:
                continue

            # Sort by resolution, prefer 1080p
            hd_files.sort(key=lambda f: abs(f.get("width", 0) - 1920))
            best = hd_files[0]
            download_url = best.get("link")
            if not download_url:
                continue

            try:
                dl_resp = requests.get(download_url, timeout=120, stream=True)
                dl_resp.raise_for_status()
                with open(output_path, "wb") as f:
                    for chunk in dl_resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                if output_path.exists() and output_path.stat().st_size > 10000:
                    return True
            except Exception:
                continue

        return False

    # ----- stock image fallback (same as before) -----

    def fetch_stock_image(self, query: str, output_path: Path, size: tuple[int, int], seed: str) -> bool:
        width, height = size
        urls = [
            f"https://picsum.photos/seed/{requests.utils.quote(seed)}/{width}/{height}",
            f"https://source.unsplash.com/random/{width}x{height}/?{requests.utils.quote(query)}",
            f"https://loremflickr.com/{width}/{height}/{requests.utils.quote(query)}?lock={requests.utils.quote(seed)}",
        ]
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        }
        for url in urls:
            try:
                response = requests.get(url, timeout=25, headers=headers)
                response.raise_for_status()
                if "image" not in response.headers.get("content-type", ""):
                    continue
                output_path.write_bytes(response.content)
                return True
            except Exception:
                continue
        return False

    # ----- scene asset generation -----

    def build_image_prompt(self, text: str) -> str:
        return self.build_scene_prompt(text)

    def build_image_query(self, text: str) -> str:
        keywords = self.extract_keywords(text, limit=4)
        if keywords:
            return ",".join(keywords)
        topic = self.scene_topic(text)
        fallback = {
            "space": "space,galaxy,stars",
            "history": "ancient,temple,ruins",
            "future": "future,robot,city",
            "ocean": "ocean,sea,waves",
            "war": "war,battle,soldiers",
            "documentary": "cinematic,documentary,nature",
        }
        return fallback.get(topic, "cinematic,documentary")

    def classify_scene_style(self, text: str) -> str:
        t = text.lower()
        keywords = {
            "space": ["vũ trụ", "hành tinh", "không gian", "sao", "thiên hà", "trái đất", "mặt trăng"],
            "history": ["cổ đại", "kim tự tháp", "ai cập", "đền", "đế chế", "thần thoại", "di tích"],
            "future": ["tương lai", "robot", "ai", "tàu", "trạm", "neon", "thành phố"],
            "ocean": ["biển", "đại dương", "sóng", "nước", "tàu ngầm"],
            "war": ["chiến tranh", "trận", "quân", "binh", "xâm lược"],
        }
        for style, words in keywords.items():
            if any(w in t for w in words):
                return style
        return "documentary"

    def base_palette(self, style: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
        palettes = {
            "space": ((8, 10, 20), (40, 60, 120)),
            "history": ((25, 18, 10), (130, 90, 40)),
            "future": ((8, 12, 16), (40, 180, 220)),
            "ocean": ((4, 14, 28), (20, 90, 150)),
            "war": ((18, 12, 12), (120, 50, 50)),
            "documentary": ((8, 10, 18), (60, 80, 120)),
        }
        return palettes.get(style, palettes["documentary"])

    def make_scene_plate(self, chapter: Chapter, scene: Scene, size: tuple[int, int], chapter_index: int, scene_index: int) -> Path:
        """Fallback: create a static image plate when no stock video available."""
        width, height = size
        style = self.classify_scene_style(scene.text)
        query = self.build_image_query(scene.text)
        seed = f"{chapter_index:03d}-{scene_index:02d}-{query}"
        path = self.chapters_dir / f"chapter_{chapter_index:03d}_scene_{scene_index:02d}.png"

        if not self.fetch_stock_image(query, path, size, seed):
            top_color, bottom_color = self.base_palette(style)
            img = Image.new("RGB", size, top_color)
            draw = ImageDraw.Draw(img)
            for y in range(height):
                t = y / max(1, height - 1)
                r = int(top_color[0] * (1 - t) + bottom_color[0] * t)
                g = int(top_color[1] * (1 - t) + bottom_color[1] * t)
                b = int(top_color[2] * (1 - t) + bottom_color[2] * t)
                draw.line((0, y, width, y), fill=(r, g, b))
        else:
            with Image.open(path) as source:
                img = source.convert("RGB")
                img = img.resize(size, Image.Resampling.LANCZOS)

        img.convert("RGB").save(path, quality=95)
        return path

    def make_scene_clip_from_video(
        self,
        scene: Scene,
        chapter_index: int,
        scene_index: int,
        duration: float,
    ) -> Optional[Path]:
        """Try to download a stock video clip and trim it for this scene."""
        if not self.config.pexels_api_key:
            return None

        search_query = self.build_video_search_query(scene.text)
        raw_video = self.videos_dir / f"raw_ch{chapter_index:03d}_sc{scene_index:02d}.mp4"

        # Use different page for different scenes to get variety
        page = ((chapter_index - 1) * 4 + scene_index) % 5 + 1

        if not self.fetch_pexels_video(
            query=search_query,
            output_path=raw_video,
            min_duration=max(5.0, duration * 0.3),
            target_duration=duration + 5,
            page=page,
        ):
            return None

        # Trim and resize the video to exact duration
        width, height = self.parse_resolution(self.config.resolution)
        clip_path = self.render_dir / f"clip_{chapter_index:03d}_{scene_index:02d}.mp4"

        # Get source video duration
        probe_cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            str(raw_video),
        ]
        try:
            probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
            probe_data = json.loads(probe_result.stdout)
            src_duration = float(probe_data.get("format", {}).get("duration", 0))
        except Exception:
            src_duration = duration

        # Calculate start time (use different offsets for variety)
        max_start = max(0, src_duration - duration)
        start_offset = min(max_start, (scene_index * 2.5) % max(1, max_start))

        # Build FFmpeg command: trim, scale, crop to exact resolution, color grade
        vf_parts = [
            f"scale={width}:{height}:force_original_aspect_ratio=increase",
            f"crop={width}:{height}",
            "eq=contrast=1.06:saturation=1.08:brightness=-0.02",
            "format=yuv420p",
        ]
        vf = ",".join(vf_parts)

        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{start_offset:.3f}",
            "-i", str(raw_video),
            "-t", f"{duration:.3f}",
            "-vf", vf,
            "-an",
            "-r", str(self.config.fps),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            str(clip_path),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            if clip_path.exists() and clip_path.stat().st_size > 1000:
                return clip_path
        except Exception:
            pass
        finally:
            try:
                if raw_video.exists():
                    raw_video.unlink()
            except Exception:
                pass
        return None

    def make_motion_clip(
        self,
        image_path: Path,
        duration: float,
        output_path: Path,
        scene_index: int = 1,
        is_key_scene: bool = False,
        fast_render: bool = False,
    ) -> None:
        """Create a motion clip from a static image (Ken Burns effect) — fallback."""
        width, height = self.parse_resolution(self.config.resolution)
        fade_out = max(0.35, min(0.7, duration * 0.10))
        zoom_start = 1.03 if fast_render else (1.06 if is_key_scene else 1.04)
        zoom_end = 1.08 if fast_render else (1.13 if is_key_scene else 1.09)
        pan_x = "(iw-iw/zoom)/2"
        pan_y = "(ih-ih/zoom)/2"
        if not fast_render:
            if scene_index % 3 == 0:
                pan_x = "(iw-iw/zoom)*0.18"
            elif scene_index % 3 == 1:
                pan_x = "(iw-iw/zoom)*0.55"
            else:
                pan_x = "(iw-iw/zoom)*0.35"
        zoom_expr = f"min(zoom+({zoom_end - zoom_start})/({max(duration * self.config.fps - 1, 1)}),{zoom_end})"
        vf_parts = [
            f"scale={width}:{height}:force_original_aspect_ratio=increase",
            f"crop={width}:{height}",
            f"zoompan=z='if(lte(on,1),{zoom_start:.3f},{zoom_expr})':x='{pan_x}':y='{pan_y}':d=1:s={width}x{height}:fps={self.config.fps}",
            f"fade=t=in:st=0:d={0.25 if fast_render else 0.45}",
            f"fade=t=out:st={max(duration - fade_out, 0):.3f}:d={fade_out}",
        ]
        if not fast_render:
            vf_parts.append("eq=contrast=1.05:saturation=1.06:brightness=-0.01")
        vf_parts.append("format=yuv420p")
        vf = ",".join(vf_parts)
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", str(image_path),
            "-t", f"{duration:.3f}",
            "-r", str(self.config.fps),
            "-vf", vf,
            "-pix_fmt", "yuv420p",
            str(output_path),
        ]
        subprocess.run(cmd, check=True)

    # ----- slide / clip generation -----

    def generate_slides(self, chapters: List[Chapter]) -> List[Path]:
        """Generate scene assets — either stock video clips or static image plates."""
        width, height = self.parse_resolution(self.config.resolution)
        slide_paths: List[Path] = []
        use_video = bool(self.config.pexels_api_key)

        for cidx, chapter in enumerate(chapters, start=1):
            scenes = chapter.scenes or [Scene(title="Scene 1", start_sec=chapter.start_sec, end_sec=chapter.end_sec, text=chapter.script, prompt=chapter.image_prompt)]
            for sidx, scene in enumerate(scenes, start=1):
                scene = self.hydrate_scene(scene)
                duration = max(4.0, scene.end_sec - scene.start_sec)

                clip_path = None
                if use_video:
                    print(f"  Downloading stock video for Chapter {cidx}, Scene {sidx}...")
                    clip_path = self.make_scene_clip_from_video(scene, cidx, sidx, duration)
                    if clip_path:
                        print(f"    [OK] Got video clip: {clip_path.name}")
                        scene.clip_path = str(clip_path)
                        slide_paths.append(clip_path)
                        continue
                    else:
                        print(f"    [INFO] No video found, falling back to image plate")

                # Fallback to static image
                image_path = self.make_scene_plate(chapter, scene, (width, height), cidx, sidx)
                slide_paths.append(image_path)
                scene.image_path = str(image_path)
        return slide_paths

    # ----- timeline / rendering -----

    def build_timeline(self, chapters: List[Chapter]) -> List[Scene]:
        timeline: List[Scene] = []
        for chapter in chapters:
            scenes = chapter.scenes or [Scene(title="Scene 1", start_sec=chapter.start_sec, end_sec=chapter.end_sec, text=chapter.script, prompt=chapter.image_prompt)]
            timeline.extend(scenes)
        return timeline

    def parse_resolution(self, resolution: str) -> tuple[int, int]:
        w, h = resolution.lower().split("x", 1)
        return int(w), int(h)

    def render_video(self, chapters: List[Chapter], slides: List[Path], fast_render: bool = False) -> Path:
        if not self.config.voice_path.exists():
            raise FileNotFoundError(f"Voice file not found: {self.config.voice_path}")
        if not slides:
            raise ValueError("No slide images generated")

        timeline = self.build_timeline(chapters)
        if len(slides) < len(timeline):
            raise ValueError(f"Not enough slides generated: got {len(slides)}, expected {len(timeline)}")

        clip_paths: List[Path] = []
        for idx, (scene, slide_path) in enumerate(zip(timeline, slides), start=1):
            duration = max(4.0, scene.end_sec - scene.start_sec)

            # Check if slide is already a video clip (from Pexels)
            if slide_path.suffix.lower() == ".mp4":
                # Already a video clip — just use it directly
                clip_paths.append(slide_path)
            else:
                # Static image — create motion clip
                clip_path = self.render_dir / f"slide_{idx:03d}.mp4"
                self.make_motion_clip(
                    slide_path,
                    duration,
                    clip_path,
                    scene_index=idx,
                    is_key_scene=scene.is_key_scene,
                    fast_render=fast_render,
                )
                clip_paths.append(clip_path)

        if not clip_paths:
            raise ValueError("No video clips were generated")

        # Concatenate clips with crossfade transitions
        video_no_audio = self.render_dir / "video_no_audio.mp4"
        try:
            self._concat_with_crossfade(clip_paths, video_no_audio, crossfade_duration=0.6)

            # Merge with voice audio (and optional background music)
            final_output = self.output_dir / f"{self.config.project_name}.mp4"
            self._merge_audio_video(video_no_audio, final_output, fast_render)
            return final_output
        finally:
            # Clean up video_no_audio.mp4
            try:
                if video_no_audio.exists():
                    video_no_audio.unlink()
            except Exception:
                pass
            # Clean up generated motion clips (those under self.render_dir / slide_*.mp4)
            for path in clip_paths:
                try:
                    if path.exists() and path.parent == self.render_dir:
                        path.unlink()
                except Exception:
                    pass

    def _concat_with_crossfade(
        self,
        clip_paths: List[Path],
        output_path: Path,
        crossfade_duration: float = 0.6,
    ) -> None:
        """Concatenate video clips with crossfade transitions using xfade filter."""
        if len(clip_paths) == 1:
            # Single clip, just copy
            subprocess.run(["ffmpeg", "-y", "-i", str(clip_paths[0]), "-c", "copy", str(output_path)], check=True)
            return

        if len(clip_paths) == 2:
            # Simple two-clip crossfade
            dur0 = self._get_video_duration(clip_paths[0])
            offset = max(0, dur0 - crossfade_duration)
            cmd = [
                "ffmpeg", "-y",
                "-i", str(clip_paths[0]),
                "-i", str(clip_paths[1]),
                "-filter_complex",
                f"[0:v][1:v]xfade=transition=fade:duration={crossfade_duration}:offset={offset},format=yuv420p[v]",
                "-map", "[v]",
                "-c:v", "libx264", "-preset", "fast", "-crf", "21",
                str(output_path),
            ]
            try:
                subprocess.run(cmd, check=True, capture_output=True)
                return
            except subprocess.CalledProcessError:
                pass  # Fall through to simple concat

        # For many clips, use simple concat (xfade chains get complex)
        # Add fade in/out to each clip for smooth transitions
        faded_clips: list[Path] = []
        for i, clip in enumerate(clip_paths):
            dur = self._get_video_duration(clip)
            fade_d = min(crossfade_duration, dur * 0.15)
            faded_path = clip.parent / f"faded_{i:03d}.mp4"

            vf = f"fade=t=in:st=0:d={fade_d},fade=t=out:st={max(0, dur - fade_d):.3f}:d={fade_d},format=yuv420p"
            cmd = [
                "ffmpeg", "-y",
                "-i", str(clip),
                "-vf", vf,
                "-c:v", "libx264", "-preset", "fast", "-crf", "21",
                "-an",
                str(faded_path),
            ]
            try:
                subprocess.run(cmd, check=True, capture_output=True)
                faded_clips.append(faded_path)
            except subprocess.CalledProcessError:
                faded_clips.append(clip)

        concat_file = self.render_dir / "concat.txt"
        try:
            concat_file.write_text(
                "\n".join(f"file '{p.name}'" for p in faded_clips),
                encoding="utf-8",
            )
            subprocess.run([
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", concat_file.name, "-c", "copy", str(output_path.resolve()),
            ], cwd=str(self.render_dir), check=True)
        finally:
            # Clean up faded transition clips
            for path in faded_clips:
                try:
                    if path.exists() and "faded_" in path.name:
                        path.unlink()
                except Exception:
                    pass
            # Clean up concat manifest file
            try:
                if concat_file.exists():
                    concat_file.unlink()
            except Exception:
                pass

    def _merge_audio_video(
        self,
        video_path: Path,
        output_path: Path,
        fast_render: bool = False,
    ) -> None:
        """Merge video with voice narration and optional background music."""
        voice_path = self.config.voice_path
        music_path = self.config.music_path

        if music_path and music_path.exists():
            # Mix voice + background music
            # Voice at full volume, music at ~15%
            filter_complex = (
                f"[1:a]volume=1.0[voice];"
                f"[2:a]volume=0.15,aloop=loop=-1:size=2e+09[music];"
                f"[voice][music]amix=inputs=2:duration=shortest:dropout_transition=3[aout]"
            )
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-i", str(voice_path),
                "-i", str(music_path),
                "-filter_complex", filter_complex,
                "-map", "0:v",
                "-map", "[aout]",
                "-c:v", "copy" if fast_render else "libx264",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                str(output_path),
            ]
            if not fast_render:
                cmd.extend(["-preset", "fast", "-crf", "21"])
        else:
            # Voice only
            if fast_render:
                cmd = [
                    "ffmpeg", "-y",
                    "-i", str(video_path),
                    "-i", str(voice_path),
                    "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k",
                    "-shortest",
                    str(output_path),
                ]
            else:
                cmd = [
                    "ffmpeg", "-y",
                    "-i", str(video_path),
                    "-i", str(voice_path),
                    "-map", "0:v",
                    "-map", "1:a",
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-crf", "21",
                    "-c:a", "aac", "-b:a", "192k",
                    "-shortest",
                    str(output_path),
                ]

        subprocess.run(cmd, check=True)

    def _get_video_duration(self, video_path: Path) -> float:
        """Get duration of a video file using ffprobe."""
        try:
            result = subprocess.run([
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                str(video_path),
            ], capture_output=True, text=True, check=True)
            data = json.loads(result.stdout)
            return float(data.get("format", {}).get("duration", 10))
        except Exception:
            return 10.0

    # ----- plan / manifest -----

    def generate_plan(self) -> dict:
        script = self.load_script()
        chapters = self.split_into_chapters(script)
        plan = {
            "project": self.config.project_name,
            "estimated_duration_sec": round(chapters[-1].end_sec if chapters else 0, 2),
            "chapters": [asdict(ch) for ch in chapters],
        }
        plan_path = self.output_dir / "plan.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        return plan

    def export_chapter_markers(self, chapters: List[Chapter]) -> Path:
        markers_path = self.output_dir / "markers.txt"
        lines = []
        for ch in chapters:
            lines.append(f"{self.format_timestamp(ch.start_sec)} {ch.title}")
        markers_path.write_text("\n".join(lines), encoding="utf-8")
        return markers_path

    def format_timestamp(self, seconds: float) -> str:
        total = int(math.floor(seconds))
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def load_font(self, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        candidates = [
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
            r"C:\Windows\Fonts\calibri.ttf",
        ]
        for path in candidates:
            if Path(path).exists():
                return ImageFont.truetype(path, size=size)
        return ImageFont.load_default()

    def wrap_text(self, text: str, font: ImageFont.ImageFont, max_width: int, draw: ImageDraw.ImageDraw) -> List[str]:
        words = text.split()
        lines: List[str] = []
        current = ""
        for word in words:
            test = f"{current} {word}".strip()
            if draw.textlength(test, font=font) <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    def run(self) -> None:
        plan = self.generate_plan()
        chapters = [self.hydrate_chapter(ch) for ch in plan["chapters"]]
        self.export_chapter_markers(chapters)
        self.write_manifest(chapters)
        slides = self.generate_slides(chapters)
        final_video = self.render_video(chapters, slides)
        print(f"Generated {len(slides)} scene assets in {self.chapters_dir}")
        print(f"Rendered video: {final_video}")

    def write_manifest(self, chapters: List[Chapter]) -> None:
        manifest_path = self.output_dir / "manifest.json"
        manifest = {
            "config": {
                "project_name": self.config.project_name,
                "script_path": str(self.config.script_path),
                "voice_path": str(self.config.voice_path),
                "music_path": str(self.config.music_path) if self.config.music_path else None,
                "resolution": self.config.resolution,
                "fps": self.config.fps,
            },
            "chapters": [asdict(ch) for ch in chapters],
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


# ===========================================================================
# TTS (Edge-TTS) — improved storytelling prosody
# ===========================================================================

async def _edge_tts_to_mp3(text: str, output_path: Path, voice: str, rate: str = "+0%") -> None:
    import edge_tts

    communicator = edge_tts.Communicate(text, voice=voice, rate=rate)
    await communicator.save(str(output_path))


def _normalize_tts_text(text: str) -> str:
    """Normalize and add storytelling prosody to TTS text."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"^[\-*•\d.\)\(]+\s*", "", line).strip() for line in text.split("\n")]

    # Keep storytelling rhythm from line breaks:
    # - empty line => stronger pause (use "…" ellipsis)
    # - normal new line => soft pause (use comma)
    pause_tokens: List[str] = []
    blank_streak = 0
    for line in lines:
        if not line:
            blank_streak += 1
            continue
        if pause_tokens:
            if blank_streak > 0:
                pause_tokens.append(" … ")
            else:
                pause_tokens.append(", ")
        pause_tokens.append(line)
        blank_streak = 0

    text = "".join(pause_tokens)

    # Gentle prosody polish for Vietnamese storytelling.
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\.{3,}", "…", text)
    text = re.sub(r"\s*([,;:.!?…])\s*", r"\1 ", text)
    text = re.sub(r"\s+", " ", text).strip()

    # Add dramatic pauses before emotional phrases
    dramatic_markers = [
        "nhưng", "và rồi", "tuy nhiên", "thế nhưng",
        "điều đáng sợ", "điều kỳ lạ", "sự thật",
        "có lẽ", "nói cách khác",
    ]
    for marker in dramatic_markers:
        # Add a soft pause (ellipsis) before dramatic phrases
        pattern = re.compile(r"(?<=[.!?…])\s+(" + re.escape(marker) + r")", re.IGNORECASE)
        text = pattern.sub(r" … \1", text)

    # If there are very long spans without sentence-ending punctuation,
    # add soft pauses to prevent monotone run-on delivery.
    segments = re.split(r"([.!?…])", text)
    rebuilt: List[str] = []
    for i in range(0, len(segments), 2):
        part = segments[i].strip()
        punct = segments[i + 1] if i + 1 < len(segments) else ""
        if part and punct == "":
            words = part.split()
            if len(words) > 28:
                mid = len(words) // 2
                part = " ".join(words[:mid]) + ", " + " ".join(words[mid:])
        if part:
            rebuilt.append(part)
        if punct:
            rebuilt.append(punct)
    text = " ".join(rebuilt)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _split_tts_chunks(text: str, max_chars: int = 360) -> List[str]:
    text = _normalize_tts_text(text)
    if not text:
        return []

    parts = [p.strip() for p in re.split(r"(?<=[.!?…])\s+", text) if p.strip()]
    if not parts:
        parts = [text]

    chunks: List[str] = []
    current = ""
    for part in parts:
        segments = [s.strip() for s in re.split(r",|;|:\s+", part) if s.strip()] or [part]
        for segment in segments:
            candidate = f"{current} {segment}".strip() if current else segment
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                if len(segment) > max_chars:
                    words = segment.split()
                    buffer = ""
                    for word in words:
                        cand = f"{buffer} {word}".strip() if buffer else word
                        if len(cand) <= max_chars:
                            buffer = cand
                        else:
                            if buffer:
                                chunks.append(buffer)
                            buffer = word
                    current = buffer
                else:
                    current = segment
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk.strip()]


def _run_async(coro):
    """Safely run an async coroutine, cleaning up pending tasks to avoid loop-closed warnings."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        try:
            pending = asyncio.all_tasks(loop)
            if pending:
                for task in pending:
                    task.cancel()
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        finally:
            loop.close()


def _ensure_valid_voice(voice: str) -> str:
    choices = get_supported_voice_choices()
    requested = (voice or "").strip()
    return requested if requested in choices else choices[0]


def _generate_voice_chunk(chunk: str, chunk_file: Path, voice: str, rate: str = "+0%", retries: int = 3) -> None:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            _run_async(_edge_tts_to_mp3(chunk, chunk_file, voice, rate=rate))
            if chunk_file.exists() and chunk_file.stat().st_size > 0:
                return
            raise RuntimeError("Edge-TTS produced an empty file")
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))
    if last_error:
        raise last_error


def get_supported_voice_choices() -> List[str]:
    # Keep a curated list of Vietnamese voices that are commonly available.
    return [
        "vi-VN-HoaiMyNeural",
        "vi-VN-NamMinhNeural",
    ]


def _get_runtime_vi_voices() -> List[str]:
    """Best-effort fetch of currently available Vietnamese Edge voices."""
    try:
        import edge_tts

        voices = _run_async(edge_tts.list_voices())
        names = [v.get("ShortName", "") for v in voices if isinstance(v, dict)]
        vi = [n for n in names if n.startswith("vi-VN-")]
        # Keep stable order but unique values.
        seen: set[str] = set()
        ordered: List[str] = []
        for name in vi:
            if name and name not in seen:
                seen.add(name)
                ordered.append(name)
        return ordered
    except Exception:
        return []


def _script_cache_key(text: str, voice: str, rate: str, max_chars: int, workers: int) -> str:
    payload = f"voice={voice}\nrate={rate}\nmax_chars={max_chars}\nworkers={workers}\n{text}".encode("utf-8")
    return hashlib.sha1(payload).hexdigest()


def _generate_voice_chunk_with_voice(
    chunk: str,
    chunk_file: Path,
    voice: str,
    rate: str = "+0%",
    allow_fallback: bool = True,
) -> str:
    if not allow_fallback:
        _generate_voice_chunk(chunk, chunk_file, voice, rate=rate)
        return voice

    runtime_voices = _get_runtime_vi_voices()
    fallback_order = [
        voice,
        "vi-VN-NamMinhNeural",
        "vi-VN-HoaiMyNeural",
    ]
    fallback_order.extend(runtime_voices)
    fallback_order.extend([
        "en-US-GuyNeural",
        "en-US-AriaNeural",
    ])

    ordered_candidates: List[str] = []
    seen: set[str] = set()
    for candidate in fallback_order:
        c = (candidate or "").strip()
        if c and c not in seen:
            seen.add(c)
            ordered_candidates.append(c)

    errors: List[str] = []
    for candidate_voice in ordered_candidates:
        try:
            _generate_voice_chunk(chunk, chunk_file, candidate_voice, rate=rate)
            return candidate_voice
        except Exception as exc:
            errors.append(f"{candidate_voice}: {exc}")
            continue

    if chunk_file.exists():
        chunk_file.unlink()
    tail = "; ".join(errors[-3:])
    raise RuntimeError(
        f"Unable to generate TTS audio for {chunk_file.name} (requested '{voice}'). Tried {len(ordered_candidates)} voices. Last errors: {tail}"
    )


def _apply_voice_polish(input_mp3: Path, output_mp3: Path) -> None:
    """Apply free FFmpeg-based vocal polish.

    Makes the voice warmer, fuller and more broadcast-like.
    Includes subtle reverb for a cinematic narrator feel.
    """
    temp_output = output_mp3.with_suffix(".polished.mp3")
    filter_chain = (
        "highpass=f=80,"
        "equalizer=f=120:width_type=q:width=1.0:g=2.5,"
        "equalizer=f=3000:width_type=q:width=1.0:g=-2.0,"
        "equalizer=f=8000:width_type=q:width=1.0:g=1.5,"
        "acompressor=threshold=-16dB:ratio=2.5:attack=10:release=120:makeup=2.0,"
        "aecho=0.85:0.75:25:0.18,"
        "loudnorm=I=-16:TP=-1.5:LRA=11"
    )
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(input_mp3),
        "-af", filter_chain,
        "-codec:a", "libmp3lame",
        "-q:a", "2",
        str(temp_output),
    ], check=True)
    if not temp_output.exists() or temp_output.stat().st_size == 0:
        raise RuntimeError("Failed to polish voice audio")
    if output_mp3.exists():
        output_mp3.unlink()
    temp_output.replace(output_mp3)


def generate_voice_mp3(
    text_path: Path,
    output_mp3: Path,
    voice: str = "vi-VN-NamMinhNeural",
    rate: str = "-10%",
    workers: int = 2,
    max_chars: int = 360,
    use_cache: bool = True,
    polish: bool = True,
    allow_fallback_voices: bool = True,
) -> Path:
    """Generate MP3 voiceover from a text file using Edge-TTS.

    Uses limited parallelism and caching for speed while keeping reliability.
    Applies a free FFmpeg polish pass to make the voice warmer and more broadcast-like.
    Requires: pip install edge-tts
    Internet connection is required.
    """
    text = text_path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError("Script file is empty")

    output_mp3.parent.mkdir(parents=True, exist_ok=True)
    chunks = _split_tts_chunks(text, max_chars=max_chars)
    if not chunks:
        raise ValueError("Script file is empty after normalization")

    cache_key = _script_cache_key(text, voice, rate, max_chars, workers)
    cache_dir = output_mp3.parent / "tts_cache" / cache_key
    cache_mp3 = cache_dir / "voice.mp3"
    if use_cache and cache_mp3.exists() and cache_mp3.stat().st_size > 0:
        output_mp3.write_bytes(cache_mp3.read_bytes())
        return output_mp3

    temp_dir = output_mp3.parent / "tts_chunks" / cache_key
    temp_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    normalized_voice = _ensure_valid_voice(voice)
    chunk_specs = [(idx, chunk) for idx, chunk in enumerate(chunks, start=1)]
    generated_files: list[Path] = []
    max_workers = max(1, min(int(workers or 1), 4))

    try:
        if max_workers == 1 or len(chunk_specs) == 1:
            for idx, chunk in chunk_specs:
                chunk_file = temp_dir / f"chunk_{idx:03d}.mp3"
                _generate_voice_chunk_with_voice(
                    chunk,
                    chunk_file,
                    normalized_voice,
                    rate=rate,
                    allow_fallback=allow_fallback_voices,
                )
                generated_files.append(chunk_file)
        else:
            # Keep parallelism small to avoid slowdowns from excessive TTS contention.
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {
                    executor.submit(
                        _generate_voice_chunk_with_voice,
                        chunk,
                        temp_dir / f"chunk_{idx:03d}.mp3",
                        normalized_voice,
                        rate,
                        allow_fallback_voices,
                    ): idx
                    for idx, chunk in chunk_specs
                }
                for future in as_completed(future_map):
                    idx = future_map[future]
                    future.result()
                    generated_files.append(temp_dir / f"chunk_{idx:03d}.mp3")

        generated_files = sorted(generated_files, key=lambda p: p.name)
        concat_file = temp_dir / "concat.txt"
        concat_file.write_text("\n".join(f"file '{p.name}'" for p in generated_files), encoding="utf-8")
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file.name, "-c", "copy", str(output_mp3.resolve())
        ], cwd=str(temp_dir), check=True)
        if not output_mp3.exists() or output_mp3.stat().st_size == 0:
            raise RuntimeError("Failed to merge TTS chunks into output voice file")
        if polish:
            polished_output = output_mp3.with_suffix(".polished.mp3")
            _apply_voice_polish(output_mp3, polished_output)
            polished_output.replace(output_mp3)
        if use_cache:
            cache_mp3.write_bytes(output_mp3.read_bytes())
        return output_mp3
    except ModuleNotFoundError as exc:
        raise RuntimeError("Missing dependency: edge-tts. Install it with pip install edge-tts") from exc
    except Exception:
        if output_mp3.exists():
            output_mp3.unlink()
        raise


# ===========================================================================
# CLI
# ===========================================================================

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stock-video narration pipeline")
    parser.add_argument("--project-name", default="long_form_video")
    parser.add_argument("--script", required=True)
    parser.add_argument("--voice")
    parser.add_argument("--output-dir", default=r"E:\Project_ItWebDev\Python\ren-video\output")
    parser.add_argument("--resolution", default="1920x1080")
    parser.add_argument("--pexels-api-key", default="FmIsmwl6a3xuPdRiRlXwzioCXMjkX7PAEUfSJ1CStBPUosglp7rscxny", help="Pexels API key for stock video download")
    parser.add_argument("--generate-voice", action="store_true", help="Generate voice MP3 from script before building plan")
    parser.add_argument("--tts-voice", default="vi-VN-NamMinhNeural", help="Edge-TTS voice name")
    parser.add_argument("--tts-rate", default="-10%", help="Edge-TTS speaking rate (slower = more narrative)")
    parser.add_argument("--tts-workers", type=int, default=2, help="Parallel TTS workers")
    parser.add_argument("--tts-chunk-size", type=int, default=360, help="Chunk size in characters")
    parser.add_argument("--tts-no-cache", action="store_true", help="Disable cached generated voice reuse")
    parser.add_argument("--tts-no-polish", action="store_true", help="Skip voice audio polishing")
    parser.add_argument("--render-video", action="store_true", help="Render video with voice")
    return parser


def main() -> None:
    import shutil
    args = build_arg_parser().parse_args()
    script_path = Path(args.script)
    output_dir = Path(args.output_dir)

    # Check for Pexels API key from arg or environment variable
    pexels_key = args.pexels_api_key or os.environ.get("PEXELS_API_KEY", "")

    if script_path.is_dir():
        # Batch mode: process all .txt files in the directory
        txt_files = sorted(list(script_path.glob("*.txt")))
        if not txt_files:
            print(f"No .txt files found in directory: {script_path}")
            return

        done_dir = script_path / "done"
        done_dir.mkdir(exist_ok=True)

        print(f"Found {len(txt_files)} script files to process.")
        for idx, file in enumerate(txt_files, start=1):
            name = file.stem
            file_output_dir = output_dir / name
            final_video = file_output_dir / f"{name}.mp4"

            # Check if video already exists to avoid re-rendering
            if final_video.exists() and final_video.stat().st_size > 1000:
                print(f"[{idx}/{len(txt_files)}] Video for '{file.name}' already exists. Skipping...")
                try:
                    shutil.move(str(file), str(done_dir / file.name))
                except Exception as e:
                    print(f"Failed to move '{file.name}' to done: {e}")
                continue

            print(f"\n==================================================")
            print(f"[{idx}/{len(txt_files)}] Processing script: {file.name}")
            print(f"==================================================")

            file_output_dir.mkdir(parents=True, exist_ok=True)
            voice_path = file_output_dir / "voice.mp3"

            try:
                if args.generate_voice:
                    print(f"Generating voice to {voice_path} using voice '{args.tts_voice}' ...")
                    generate_voice_mp3(
                        file,
                        voice_path,
                        args.tts_voice,
                        rate=args.tts_rate,
                        workers=args.tts_workers,
                        max_chars=args.tts_chunk_size,
                        use_cache=not args.tts_no_cache,
                        polish=not args.tts_no_polish,
                    )

                if not voice_path.exists():
                    print(f"Error: Voice file not found for '{file.name}', skipping.")
                    continue

                config = ProjectConfig(
                    project_name=name,
                    output_dir=file_output_dir,
                    script_path=file,
                    voice_path=voice_path,
                    resolution=args.resolution,
                    pexels_api_key=pexels_key,
                )
                pipeline = VideoPipeline(config)
                plan = pipeline.generate_plan()
                chapters = [pipeline.hydrate_chapter(ch) for ch in plan["chapters"]]
                pipeline.export_chapter_markers(chapters)
                pipeline.write_manifest(chapters)
                slides = pipeline.generate_slides(chapters)
                
                if args.render_video:
                    rendered_file = pipeline.render_video(chapters, slides)
                    print(f"Rendered video successfully: {rendered_file}")
                    
                    # Move script to done folder
                    try:
                        shutil.move(str(file), str(done_dir / file.name))
                        print(f"Moved script '{file.name}' to '{done_dir.name}/'")
                    except Exception as e:
                        print(f"Failed to move '{file.name}' to done: {e}")
                else:
                    print(f"Generated {len(slides)} scene assets in {file_output_dir}")
                    print(f"Voice narration ready at: {voice_path}")

            except Exception as e:
                print(f"Error processing script '{file.name}': {e}")
                import traceback
                traceback.print_exc()
    else:
        # Single file mode (original behavior)
        voice_path = Path(args.voice) if args.voice else output_dir / "voice.mp3"
        if args.generate_voice:
            print(f"Generating voice to {voice_path} using voice '{args.tts_voice}' ...")
            generate_voice_mp3(
                script_path,
                voice_path,
                args.tts_voice,
                rate=args.tts_rate,
                workers=args.tts_workers,
                max_chars=args.tts_chunk_size,
                use_cache=not args.tts_no_cache,
                polish=not args.tts_no_polish,
            )

        if not voice_path.exists():
            raise FileNotFoundError(f"Voice file not found: {voice_path}")

        config = ProjectConfig(
            project_name=args.project_name,
            output_dir=output_dir,
            script_path=script_path,
            voice_path=voice_path,
            resolution=args.resolution,
            pexels_api_key=pexels_key,
        )
        pipeline = VideoPipeline(config)
        plan = pipeline.generate_plan()
        chapters = [pipeline.hydrate_chapter(ch) for ch in plan["chapters"]]
        pipeline.export_chapter_markers(chapters)
        pipeline.write_manifest(chapters)
        slides = pipeline.generate_slides(chapters)
        if args.render_video:
            final_video = pipeline.render_video(chapters, slides)
            print(f"Rendered video: {final_video}")
        else:
            print(f"Generated {len(slides)} scene assets in {output_dir}")
            print(f"Voice narration ready at: {voice_path}")


if __name__ == "__main__":
    main()
