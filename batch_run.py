import os
import sys
import shutil
import subprocess
from pathlib import Path

def main():
    scripts_dir = Path("scripts")
    done_dir = scripts_dir / "done"
    done_dir.mkdir(exist_ok=True)
    
    # Lấy toàn bộ các file .txt trong thư mục scripts (không tính thư mục con)
    script_files = sorted([p for p in scripts_dir.glob("*.txt") if p.is_file()])
    
    if not script_files:
        print("Không tìm thấy kịch bản (.txt) nào trong thư mục scripts/ để xử lý.")
        return
        
    print(f"Tìm thấy {len(script_files)} kịch bản đang đợi xử lý.")
    
    for idx, script_path in enumerate(script_files, start=1):
        name = script_path.stem
        print(f"\n==================================================")
        print(f"[{idx}/{len(script_files)}] BẮT ĐẦU XỬ LÝ: {script_path.name}")
        print(f"==================================================")
        
        output_dir = Path("output") / name
        output_dir.mkdir(parents=True, exist_ok=True)
        video_path = output_dir / f"{name}.mp4"
        
        # 1. Chạy render video bằng Docker
        pipeline_cmd = [
            "docker", "run", "--rm",
            "-e", "PYTHONUNBUFFERED=1",
            "-v", f"{Path.cwd()}/scripts:/app/scripts",
            "-v", f"{Path.cwd()}/output:/app/output",
            "video-renderer",
            "--script", f"/app/scripts/{script_path.name}",
            "--output-dir", f"/app/output/{name}",
            "--project-name", name,
            "--generate-voice",
            "--render-video"
        ]
        
        print(f"-> Đang bắt đầu render video...")
        try:
            subprocess.run(pipeline_cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"[LỖI] Quá trình render video cho '{script_path.name}' thất bại: {e}")
            continue
            
        if not video_path.exists():
            print(f"[LỖI] Không tìm thấy file video đầu ra tại: {video_path}")
            continue
            
        # Đọc dòng đầu tiên của kịch bản để làm tiêu đề YouTube nếu có dấu #
        title = name
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
                if first_line.startswith("#"):
                    title = first_line.lstrip("#").strip()
        except Exception:
            pass
            
        description = f"Video truyện kể '{title}' được tự động render và tải lên bởi hệ thống."
        
        # Gọi Gemini tự động sinh SEO Title & Description nếu có API Key
        from script_generator import load_env, generate_youtube_metadata
        load_env()
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        if gemini_key:
            print("-> Đang gọi Gemini tự động tối ưu tiêu đề và mô tả chuẩn SEO...")
            seo_title, seo_desc = generate_youtube_metadata(script_path, gemini_key)
            if seo_title and seo_desc:
                title = seo_title
                description = seo_desc
                print(f"   [SEO Title]: {title}")

        # 2. Upload video lên YouTube
        print(f"-> Đang tải video lên YouTube...")
        upload_cmd = [
            sys.executable, "youtube_uploader.py",
            str(video_path),
            "--title", title,
            "--description", description,
            "--privacy", "private"
        ]
        
        try:
            subprocess.run(upload_cmd, check=True)
            print(f"[OK] Đã upload thành công kịch bản '{script_path.name}' lên YouTube.")
        except subprocess.CalledProcessError as e:
            print(f"[LỖI] Quá trình upload video lên YouTube thất bại: {e}")
            
        # 3. Di chuyển kịch bản vào thư mục done
        try:
            shutil.move(str(script_path), str(done_dir / script_path.name))
            print(f"✓ Đã chuyển kịch bản '{script_path.name}' vào thư mục done.")
        except Exception as e:
            print(f"[LỖI] Không thể di chuyển kịch bản vào thư mục done: {e}")
            
    print(f"\n===== HOÀN THÀNH TOÀN BỘ DANH SÁCH KỊCH BẢN! =====")

if __name__ == "__main__":
    main()
