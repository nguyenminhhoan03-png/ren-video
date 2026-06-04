import os
import sys
import subprocess
import argparse
from pathlib import Path
import re
import shutil
from script_generator import generate_script, load_env, generate_youtube_metadata

def main():
    load_env()
    parser = argparse.ArgumentParser(description="Chạy hàng loạt ý tưởng tự động (Queue Runner)")
    parser.add_argument("--chapters", type=int, default=8, help="Số chương muốn tạo cho mỗi kịch bản (mặc định: 8)")
    parser.add_argument("--privacy", default="private", choices=["private", "public", "unlisted"], help="Trạng thái video YouTube (mặc định: private)")
    parser.add_argument("--split-parts", type=int, default=0, help="Chia nhỏ kịch bản thành N phần để render (mặc định: 0)")
    
    args = parser.parse_args()
    chapters = args.chapters
    privacy = args.privacy
    split_parts = args.split_parts

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        print("[LỖI] Bạn chưa thiết lập biến môi trường GEMINI_API_KEY.")
        sys.exit(1)

    ideas_file = Path("ideas.txt")
    if not ideas_file.exists():
        # Tạo file mẫu nếu chưa tồn tại
        with open(ideas_file, "w", encoding="utf-8") as f:
            f.write("# Nhập danh sách ý tưởng ở đây, mỗi dòng một ý tưởng.\n")
            f.write("# Dòng có dấu # ở đầu sẽ bị bỏ qua.\n")
            f.write("Một ngày Trái Đất đột nhiên mất trọng lực trong 5 phút...\n")
        print(f"[INFO] Đã tạo file danh sách ý tưởng trống tại: {ideas_file.resolve()}")
        print("Vui lòng mở file ideas.txt lên ghi các ý tưởng vào rồi chạy lại lệnh.")
        return

    # Đọc danh sách ý tưởng
    with open(ideas_file, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    ideas = []
    for line in lines:
        line_strip = line.strip()
        if line_strip and not line_strip.startswith("#"):
            ideas.append(line_strip)

    if not ideas:
        print("[INFO] Không tìm thấy ý tưởng hợp lệ nào trong file ideas.txt.")
        return

    print(f"[START] Tìm thấy {len(ideas)} ý tưởng trong hàng đợi. Bắt đầu chạy tự động...")

    for idx, idea in enumerate(ideas, start=1):
        print(f"\n==========================================================================")
        print(f"[{idx}/{len(ideas)}] TIẾN TRÌNH: '{idea}'")
        print(f"==========================================================================")

        # 1. Sinh kịch bản
        print("\n-> Bước 1: Sinh kịch bản bằng Gemini...")
        script_path = generate_script(idea=idea, api_key=gemini_key, num_chapters=chapters, output_dir="scripts")
        if not script_path or not Path(script_path).exists():
            print(f"[LỖI] Sinh kịch bản thất bại cho ý tưởng: {idea}. Chuyển sang ý tưởng tiếp theo.")
            continue

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
            print(f"  [Cảnh báo] Không đọc được tiêu đề kịch bản: {e}")

        # 2. Chạy render video (Chạy trực tiếp nếu đang trong container Docker, ngược lại gọi Docker)
        print("\n-> Bước 2: Chạy render video...")
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
                print(f"[LỖI] Render video trực tiếp thất bại: {e}. Chuyển sang ý tưởng tiếp theo.")
                continue
        else:
            # Chạy qua lệnh docker trên host
            docker_cmd = [
                "docker", "run", "--rm",
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
                print(f"[LỖI] Render video qua Docker thất bại: {e}. Chuyển sang ý tưởng tiếp theo.")
                continue

        # 3. Tải video lên YouTube
        video_path = Path("output") / project_name / f"{project_name}.mp4"
        if not video_path.exists():
            print(f"[LỖI] Không tìm thấy file video thành phẩm: {video_path}. Chuyển sang ý tưởng tiếp theo.")
            continue

        print("\n-> Bước 3: Tải video lên YouTube...")
        title = story_title
        description = f"Video câu chuyện '{story_title}' được tự động viết kịch bản bởi Gemini, render và tải lên bởi hệ thống AI tự động."
        
        print("  Đang gọi Gemini tự động tối ưu tiêu đề và mô tả chuẩn SEO...")
        seo_title, seo_desc = generate_youtube_metadata(script_path, gemini_key)
        if seo_title and seo_desc:
            title = seo_title
            description = seo_desc
            print(f"  [SEO Title]: {title}")

        upload_cmd = [
            sys.executable, "youtube_uploader.py",
            str(video_path),
            "--title", title,
            "--description", description,
            "--privacy", privacy
        ]

        try:
            subprocess.run(upload_cmd, check=True)
            print(f"[OK] Đã upload thành công video lên YouTube.")
        except subprocess.CalledProcessError as e:
            print(f"[LỖI] Không thể upload video lên YouTube: {e}")

        # 4. Dọn dẹp bộ nhớ
        print("\n-> Bước 4: Giải phóng bộ nhớ...")
        target_dir = Path("output") / project_name
        if target_dir.exists():
            try:
                shutil.rmtree(target_dir)
                print(f"[OK] Đã xóa thư mục trung gian: {target_dir}")
            except Exception as e:
                print(f"  [Cảnh báo] Không thể xóa thư mục: {e}")

        # 5. Cập nhật file ideas.txt (Xóa ý tưởng đã làm xong khỏi hàng đợi)
        try:
            with open(ideas_file, "r", encoding="utf-8") as f:
                current_lines = f.read().splitlines()
            
            new_lines = []
            removed = False
            for l in current_lines:
                if not removed and l.strip() == idea:
                    removed = True
                    continue
                new_lines.append(l)

            with open(ideas_file, "w", encoding="utf-8") as f:
                f.write("\n".join(new_lines) + "\n")
            print("✓ Đã cập nhật ideas.txt (Loại bỏ ý tưởng đã hoàn thành khỏi danh sách hàng đợi).")
        except Exception as e:
            print(f"  [Cảnh báo] Không thể cập nhật file ideas.txt: {e}")

    print(f"\n===== HOÀN THÀNH TOÀN BỘ HÀNG ĐỢI Ý TƯỞNG! =====")

if __name__ == "__main__":
    main()
