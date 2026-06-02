import os
import pickle
from pathlib import Path
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Danh sách quyền cần thiết để upload video lên YouTube
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def get_authenticated_service(client_secrets_file="client_secrets.json", token_file="token.pickle"):
    """Thực hiện xác thực và trả về đối tượng kết nối YouTube API."""
    credentials = None
    
    # Kiểm tra xem đã có token.pickle từ lần đăng nhập trước chưa
    if os.path.exists(token_file):
        with open(token_file, "rb") as token:
            credentials = pickle.load(token)
            
    # Nếu chưa có token hoặc token hết hạn
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            print("Token đã hết hạn, đang tự động làm mới...")
            credentials.refresh(Request())
        else:
            if not os.path.exists(client_secrets_file):
                raise FileNotFoundError(
                    f"Không tìm thấy file '{client_secrets_file}'.\n"
                    f"Bạn hãy truy cập Google Cloud Console, tạo OAuth 2.0 Client ID và tải về lưu dưới tên '{client_secrets_file}'."
                )
            
            print("Đang mở trình duyệt để xác thực tài khoản YouTube...")
            flow = InstalledAppFlow.from_client_secrets_file(client_secrets_file, SCOPES)
            credentials = flow.run_local_server(port=0)
            
        # Lưu lại thông tin đăng nhập cho lần sau
        with open(token_file, "wb") as token:
            pickle.dump(credentials, token)
            
    return build("youtube", "v3", credentials=credentials)

def upload_video(video_path, title, description, category_id="22", privacy_status="private"):
    """Tải video lên YouTube."""
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Không tìm thấy file video: {video_path}")
        
    print(f"Đang kết nối tới YouTube để chuẩn bị tải lên: {video_path.name}...")
    youtube = get_authenticated_service()
    
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": category_id, # Mặc định: 22 (People & Blogs), 27 (Education), 28 (Science & Technology)
            "tags": ["AI Video", "Narration Pipeline", "Science"]
        },
        "status": {
            "privacyStatus": privacy_status # "private" (Riêng tư), "public" (Công khai), "unlisted" (Không công khai)
        }
    }
    
    # Thiết lập luồng upload file video
    media = MediaFileUpload(
        str(video_path), 
        mimetype="video/mp4", 
        chunksize=1024*1024*5, # Tải lên từng phân đoạn 5MB
        resumable=True
    )
    
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )
    
    print("Bắt đầu tải lên YouTube... Vui lòng không tắt terminal.")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Tiến độ upload: {int(status.progress() * 100)}%")
            
    print(f"\n[OK] Đã tải lên YouTube thành công!")
    print(f"Video ID của bạn: {response['id']}")
    print(f"Link xem video: https://www.youtube.com/watch?v={response['id']}")
    return response['id']

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Upload video lên YouTube")
    parser.add_argument("video_path", help="Đường dẫn đến file video .mp4")
    parser.add_argument("--title", default="Video Render Tự Động", help="Tiêu đề video trên YouTube")
    parser.add_argument("--description", default="Video được tự động tạo và tải lên bởi hệ thống.", help="Mô tả video")
    parser.add_argument("--privacy", default="private", choices=["private", "public", "unlisted"], help="Trạng thái hiển thị (mặc định: private)")
    
    args = parser.parse_args()
    try:
        upload_video(
            video_path=args.video_path,
            title=args.title,
            description=args.description,
            privacy_status=args.privacy
        )
    except Exception as e:
        print(f"\n[LỖI] {e}")
