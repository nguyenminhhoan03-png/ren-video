import os
import re
import json
import time
import argparse
from pathlib import Path
from google import genai
from google.genai import errors

def sanitize_filename(name):
    """Làm sạch tên file để không chứa ký tự đặc biệt."""
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    return name.replace(" ", "_").lower()

def generate_content_with_retry(client, model, contents, retries=5, backoff_factor=3):
    """Gọi Gemini API và tự động thử lại nếu gặp lỗi 503 (bận) hoặc 429 (quá tải)."""
    for attempt in range(retries):
        try:
            return client.models.generate_content(model=model, contents=contents)
        except Exception as e:
            err_str = str(e).lower()
            # Kiểm tra các lỗi tạm thời như 503, 429 hoặc báo bận
            if "503" in err_str or "429" in err_str or "demand" in err_str or "unavailable" in err_str:
                sleep_time = backoff_factor ** (attempt + 1)
                print(f"  [Cảnh báo] Hệ thống bận hoặc quá tải. Đang chờ thử lại sau {sleep_time} giây...")
                time.sleep(sleep_time)
            else:
                raise e
    # Lần thử cuối cùng ngoài vòng lặp
    return client.models.generate_content(model=model, contents=contents)

def generate_script(idea, api_key, num_chapters=8, output_dir="scripts"):
    """Sinh kịch bản dài bằng Gemini API thông qua 3 bước."""
    
    # Khởi tạo client của SDK google-genai mới
    client = genai.Client(api_key=api_key)
    
    print(f"\n[Bước 1] Đang lập dàn ý chi tiết cho ý tưởng: '{idea}'...")
    
    outline_prompt = f"""
    Bạn là một nhà biên kịch tài ba chuyên viết truyện khoa học viễn tưởng kịch tính và cuốn hút để làm video kể chuyện trên YouTube.
    Hãy lập dàn ý chi tiết gồm đúng {num_chapters} chương cho ý tưởng: "{idea}".
    Dàn ý phải được trả về dưới dạng cấu trúc JSON nguyên bản (không định dạng markdown, không bao quanh bởi ```json) theo mẫu sau:
    {{
      "title": "Tên kịch bản tổng quát",
      "chapters": [
        {{
          "chapter_number": 1,
          "title": "Tên chương 1",
          "summary": "Tóm tắt tình tiết chính chương 1"
        }},
        ...
      ]
    }}
    Lưu ý: Không thêm bất kỳ văn bản giải thích nào ngoài chuỗi JSON.
    """
    
    try:
        response = generate_content_with_retry(
            client=client,
            model='gemini-2.5-flash',
            contents=outline_prompt
        )
        text = response.text.strip()
        # Loại bỏ các ký tự bọc markdown nếu có
        text = re.sub(r"^```json\s*|```$", "", text, flags=re.M).strip()
        outline = json.loads(text)
    except Exception as e:
        print(f"[LỖI] Không thể sinh dàn ý dưới dạng JSON: {e}")
        return
        
    print(f"-> Đã lập xong dàn ý: '{outline.get('title')}'")
    for ch in outline['chapters']:
        print(f"  Chương {ch['chapter_number']}: {ch['title']}")
        
    # 2. Sinh chi tiết từng chương theo vòng lặp
    full_script_content = []
    story_history = ""
    
    print(f"\n[Bước 2] Đang viết chi tiết từng chương ({num_chapters} chương)...")
    for ch in outline['chapters']:
        ch_num = ch['chapter_number']
        ch_title = ch['title']
        ch_summary = ch['summary']
        
        # Thêm khoảng nghỉ cố định 5 giây giữa các chương để tránh bị Google giới hạn tần suất (Rate Limit)
        if ch_num > 1:
            print("  [Nghỉ 5s để tránh quá tải API]...")
            time.sleep(5)
            
        print(f"  -> Đang viết Chương {ch_num}/{num_chapters}: {ch_title}...")
        
        chapter_prompt = f"""
        Bạn là nhà biên kịch kể chuyện. Hãy viết nội dung chi tiết cho Chương {ch_num} dưới đây của bộ truyện: "{outline.get('title')}".
        
        Thông tin chương này:
        - Tiêu đề chương: {ch_title}
        - Tóm tắt chương: {ch_summary}
        
        Bối cảnh câu chuyện đã diễn ra trước đó (sử dụng để viết tiếp mạch lạc):
        {story_history}
        
        Yêu cầu viết:
        1. Viết chi tiết, dài khoảng 800 - 1000 từ tiếng Việt. Văn phong kịch tính, lôi cuốn, giọng kể chuyện truyền cảm.
        2. Tự động xuống dòng phân đoạn hợp lý để thuận tiện làm slide video sau này.
        3. Không cần viết lại tiêu đề chương, đi thẳng vào nội dung kể chuyện.
        4. Không viết các câu mở đầu/kết thúc kiểu "Sau đây là chương X..." hay "Hết chương X...". Chỉ viết đúng nội dung truyện.
        """
        
        try:
            ch_response = generate_content_with_retry(
                client=client,
                model='gemini-2.5-flash',
                contents=chapter_prompt
            )
            ch_text = ch_response.text.strip()
            
            # Lưu lại nội dung của chương này
            full_script_content.append(f"Chương {ch_num}: {ch_title}\n\n{ch_text}\n\n")
            
            # Cập nhật lịch sử cốt truyện để truyền vào chương sau
            story_history += f"\n- Chương {ch_num}: {ch_summary}\nNội dung chính: {ch_text[:400]}...\n"
        except Exception as e:
            print(f"[LỖI] Gặp lỗi khi viết Chương {ch_num}: {e}")
            return
            
    # 3. Gộp và xuất file
    print(f"\n[Bước 3] Đang hoàn thiện kịch bản...")
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filename = f"{sanitize_filename(outline.get('title'))}.txt"
    output_path = Path(output_dir) / filename
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# {outline.get('title')}\n\n")
        f.write("".join(full_script_content))
        
    print(f"[OK] Đã sinh thành công kịch bản dài!")
    print(f"File lưu trữ tại: {output_path.resolve()}")
    return output_path

def generate_youtube_metadata(script_path, api_key):
    """Sử dụng Gemini để tự động tạo Tiêu đề và Mô tả tối ưu SEO từ nội dung kịch bản."""
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Lấy một phần nội dung kịch bản làm dữ liệu đầu vào cho Gemini phân tích
        sample = content[:4000]
        
        client = genai.Client(api_key=api_key)
        
        prompt = f"""
        Bạn là chuyên gia marketing và tối ưu hóa SEO YouTube. Dưới đây là nội dung kịch bản câu chuyện của video:
        ---
        {sample}
        ---
        Hãy tạo ra một tiêu đề video kích thích người xem click (High CTR) dưới 70 ký tự và một mô tả chi tiết chuẩn SEO (tóm tắt cốt truyện kịch tính khoảng 150-200 từ, kèm theo các hashtag thích hợp ở cuối).
        Trả về dưới dạng JSON nguyên bản, không dùng khối mã markdown hay ```json:
        {{
          "title": "Tiêu đề giật gân, cuốn hút ở đây",
          "description": "Mô tả chuẩn SEO chi tiết kèm hashtag ở đây"
        }}
        """
        
        response = generate_content_with_retry(
            client=client,
            model='gemini-2.5-flash',
            contents=prompt
        )
        text = response.text.strip()
        # Lọc sạch markdown nếu có
        text = re.sub(r"^```json\s*|```$", "", text, flags=re.M).strip()
        data = json.loads(text)
        return data.get("title", ""), data.get("description", "")
    except Exception as e:
        print(f"  [Cảnh báo] Lỗi sinh SEO metadata từ Gemini: {e}")
        return None, None

def load_env():
    """Tự động đọc file .env ở thư mục chạy nếu có và đưa vào os.environ."""
    try:
        from pathlib import Path
        env_path = Path(".env")
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip().strip("'\"")
    except Exception:
        pass

if __name__ == "__main__":
    load_env()
    parser = argparse.ArgumentParser(description="Tự động sinh kịch bản truyện dài bằng Gemini API")
    parser.add_argument("--idea", required=True, help="Ý tưởng câu chuyện của bạn")
    parser.add_argument("--chapters", type=int, default=8, help="Số chương muốn tạo (mặc định: 8)")
    
    args = parser.parse_args()
    
    # Lấy API key từ biến môi trường
    api_key = os.environ.get("GEMINI_API_KEY", "")
    
    if not api_key:
        print("[LỖI] Vui lòng thiết lập biến môi trường GEMINI_API_KEY hoặc tạo file .env trước khi chạy.")
        print("Cách thiết lập trên Windows (PowerShell): $env:GEMINI_API_KEY='your_key_here'")
        print("Cách thiết lập trên Linux/VPS: export GEMINI_API_KEY='your_key_here'")
    else:
        generate_script(idea=args.idea, api_key=api_key, num_chapters=args.chapters)
