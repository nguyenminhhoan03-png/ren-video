import os
import sys
import subprocess
import argparse
from pathlib import Path
import re
from script_generator import generate_script, load_env, generate_youtube_metadata

def sanitize_filename(name):
    """Làm sạch tên file tương tự script_generator.py."""
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    return name.replace(" ", "_").lower()

def main():
    load_env()
    parser = argparse.ArgumentParser(description="Pipeline tự động hoàn toàn: Tạo kịch bản -> Render video -> Tải lên YouTube")
    parser.add_argument("--idea", required=True, help="Ý tưởng hoặc chủ đề kịch bản (ví dụ: 'Truyện khoa học viễn tưởng robot nổi loạn')")
    parser.add_argument("--chapters", type=int, default=8, help="Số chương kịch bản muốn tạo (mặc định: 8, tương đương ~8000 từ)")
    parser.add_argument("--privacy", default="private", choices=["private", "public", "unlisted"], help="Trạng thái hiển thị video trên YouTube (mặc định: private)")
    parser.add_argument("--split-parts", type=int, default=0, help="Chia nhỏ kịch bản thành N phần để render sequential nhằm tiết kiệm RAM/đĩa (mặc định: 0 - không chia)")
    
    args = parser.parse_args()
    idea = args.idea
    chapters = args.chapters
    privacy = args.privacy
    split_parts = args.split_parts

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        print("[LỖI] Bạn chưa thiết lập biến môi trường GEMINI_API_KEY.")
        print("Vui lòng chạy lệnh: export GEMINI_API_KEY='key_cua_ban'")
        sys.exit(1)

    # Bước 1: Gọi Gemini API sinh kịch bản dài
    print(f"\n==============================================")
    print(f"BƯỚC 1: Sinh kịch bản dài cho ý tưởng: '{idea}'")
    print(f"==============================================")
    
    script_path = generate_script(idea=idea, api_key=gemini_key, num_chapters=chapters, output_dir="scripts")
    if not script_path or not Path(script_path).exists():
        print("[LỖI] Quá trình sinh kịch bản thất bại.")
        sys.exit(1)
        
    script_path = Path(script_path)
    project_name = script_path.stem

    # Đọc tiêu đề thực tế từ file kịch bản
    story_title = "Video Kể Chuyện Tự Động"
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
            if first_line.startswith("#"):
                story_title = first_line.lstrip("#").strip()
    except Exception as e:
        print(f"[Cảnh báo] Không đọc được tiêu đề từ kịch bản: {e}")

    print(f"\n-> Dự án kịch bản: {project_name}")
    print(f"-> Tiêu đề video: {story_title}")

    # Bước 2: Chạy render video (Chạy trực tiếp nếu đang trong container Docker, ngược lại gọi Docker)
    print(f"\n==============================================")
    print(f"BƯỚC 2: Chạy render video cho '{project_name}'")
    print(f"==============================================")
    
    if os.environ.get("RUNNING_IN_DOCKER") == "1":
        # Chạy trực tiếp qua python3 thay vì gọi Docker lồng nhau
        render_cmd = [
            sys.executable, "video_pipeline.py",
            "--script", str(script_path),
            "--output-dir", str(Path("output") / project_name),
            "--project-name", project_name,
            "--generate-voice",
            "--render-video"
        ]
        if split_parts > 1:
            render_cmd.extend(["--split-parts", str(split_parts)])
        
        print(f"  [Docker Mode] Đang chạy trực tiếp: {' '.join(render_cmd)}")
        try:
            subprocess.run(render_cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"[LỖI] Lỗi xảy ra khi chạy rendering pipeline trực tiếp: {e}")
            sys.exit(1)
    else:
        # Chạy qua lệnh docker trên host
        docker_cmd = [
            "docker", "run", "-it", "--rm",
            "-e", "PYTHONUNBUFFERED=1",
            "-v", f"{Path.cwd()}/scripts:/app/scripts",
            "-v", f"{Path.cwd()}/output:/app/output",
            "video-renderer",
            "--script", f"/app/scripts/{script_path.name}",
            "--output-dir", f"/app/output/{project_name}",
            "--project-name", project_name,
            "--generate-voice",
            "--render-video"
        ]
        if split_parts > 1:
            docker_cmd.extend(["--split-parts", str(split_parts)])
        
        print(f"  [Host Mode] Đang chạy qua Docker: {' '.join(docker_cmd)}")
        try:
            subprocess.run(docker_cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"[LỖI] Lỗi xảy ra khi chạy Docker rendering pipeline: {e}")
            sys.exit(1)

    # Bước 3: Tải video lên YouTube
    video_path = Path("output") / project_name / f"{project_name}.mp4"
    if not video_path.exists():
        print(f"[LỖI] Không tìm thấy video đầu ra tại: {video_path}")
        sys.exit(1)

    print(f"\n==============================================")
    print(f"BƯỚC 3: Tải video lên YouTube")
    print(f"==============================================")
    
    title = story_title
    description = f"Video câu chuyện '{story_title}' được tự động viết kịch bản bởi Gemini, render và tải lên bởi hệ thống AI tự động."
    
    if gemini_key:
        print("-> Đang gọi Gemini tự động tối ưu tiêu đề và mô tả chuẩn SEO...")
        seo_title, seo_desc = generate_youtube_metadata(script_path, gemini_key)
        if seo_title and seo_desc:
            title = seo_title
            description = seo_desc
            print(f"   [SEO Title]: {title}")

    upload_cmd = [
        sys.executable, "youtube_uploader.py", 
        str(video_path),
        "--title", title,
        "--description", description,
        "--privacy", privacy
    ]
    
    print(f"Đang chạy lệnh tải lên: {' '.join(upload_cmd)}")
    try:
        subprocess.run(upload_cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"[LỖI] Lỗi xảy ra khi tải video lên YouTube: {e}")
        sys.exit(1)

    # Bước 4: Dọn dẹp bộ nhớ trên VPS
    print(f"\n==============================================")
    print(f"BƯỚC 4: Dọn dẹp file trung gian trên VPS")
    print(f"==============================================")
    
    target_dir = Path("output") / project_name
    if target_dir.exists():
        try:
            import shutil
            shutil.rmtree(target_dir)
            print(f"[OK] Đã giải phóng bộ nhớ: Đã xóa thư mục {target_dir}")
        except Exception as e:
            print(f"[Cảnh báo] Không thể xóa thư mục {target_dir}: {e}")

    print(f"\n===== HOÀN THÀNH TOÀN BỘ PIPELINE TỰ ĐỘNG! =====")

if __name__ == "__main__":
    main()
