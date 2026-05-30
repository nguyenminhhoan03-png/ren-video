# Slide Narration Pipeline

Project này chuyển script kể chuyện thành các slide ảnh theo từng chapter/scene, kèm voice narration. Ảnh sẽ được lấy theo keyword/nội dung script từ nguồn miễn phí, và có thể render luôn thành video slideshow.

## File chính

- `gui.py`: giao diện Tkinter để chọn file và tạo slide + voice
- `video_pipeline.py`: logic tách chapter/scene, tạo plan, sinh ảnh slide và voice helper
- `run_gui.bat`: mở GUI nhanh trên Windows
- `requirements.txt`: dependency cần cài

## Chạy GUI

```bash
python gui.py
```

Hoặc double-click `run_gui.bat`.

## Chạy CLI

```bash
python video_pipeline.py --script path/to/script.txt --generate-voice --output-dir E:\Project_ItWebDev\Python\ren-video\output
```

## Output tạo ra

- `output/plan.json`: kế hoạch chapter/scene
- `output/manifest.json`: metadata cho project
- `output/markers.txt`: timestamp marker
- `output/chapters/*.png`: slide ảnh đã render
- `output/voice.mp3`: voice narration nếu bật tạo voice

## Ghi chú

- `voice.mp3` có thể tự tạo từ script bằng Edge-TTS
- `music` và phần render video đã được bỏ khỏi luồng chính
