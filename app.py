from flask import Flask, request, send_file, jsonify
from gtts import gTTS
import io
import subprocess
import requests
import os
import textwrap
import random

app = Flask(__name__)

@app.route('/tts', methods=['GET'])
def tts():
    text = request.args.get('text', 'hello')
    lang = request.args.get('lang', 'bn')
    tts_obj = gTTS(text=text, lang=lang)
    mp3_fp = io.BytesIO()
    tts_obj.write_to_fp(mp3_fp)
    mp3_fp.seek(0)
    return send_file(mp3_fp, mimetype='audio/mpeg')

@app.route('/create-video', methods=['POST'])
def create_video():
    data = request.get_json()
    image_urls = data.get('image_urls', [])
    audio_url = data.get('audio_url', '')
    subtitle_text = data.get('text', '')

    # Download audio
    r_audio = requests.get(audio_url)
    with open('/tmp/audio.mp3', 'wb') as f:
        f.write(r_audio.content)

    # Get audio duration
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', '/tmp/audio.mp3'],
        capture_output=True, text=True
    )
    total_duration = float(result.stdout.strip())
    per_image = total_duration / max(len(image_urls), 1)

    # Download images
    image_paths = []
    for i, url in enumerate(image_urls):
        r = requests.get(url, timeout=15)
        path = f'/tmp/img_{i}.jpg'
        with open(path, 'wb') as f:
            f.write(r.content)
        image_paths.append(path)

    # Build video segments with Ken Burns effect
    segment_files = []
    effects = [
        "zoompan=z='min(zoom+0.0015,1.3)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=125:s=1280x720",
        "zoompan=z='if(lte(zoom,1.0),1.3,max(1.001,zoom-0.0015))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=125:s=1280x720",
        "zoompan=z='min(zoom+0.0015,1.3)':x='0':y='ih/2-(ih/zoom/2)':d=125:s=1280x720",
        "zoompan=z='min(zoom+0.0015,1.3)':x='iw-(iw/zoom)':y='ih/2-(ih/zoom/2)':d=125:s=1280x720",
    ]

    for i, path in enumerate(image_paths):
        out = f'/tmp/seg_{i}.mp4'
        effect = effects[i % len(effects)]
        subprocess.run([
            'ffmpeg', '-y', '-loop', '1', '-i', path,
            '-vf', f'scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,{effect}',
            '-t', str(per_image), '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-r', '25', out
        ], capture_output=True)
        segment_files.append(out)

    # Concat segments
    list_file = '/tmp/segments.txt'
    with open(list_file, 'w') as f:
        for s in segment_files:
            f.write(f"file '{s}'\n")

    subprocess.run([
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
        '-i', list_file, '-c', 'copy', '/tmp/video_raw.mp4'
    ], capture_output=True)

    # Build subtitle file (SRT)
    words = subtitle_text.split()
    srt_lines = []
    chunk_size = 7
    chunks = [' '.join(words[i:i+chunk_size]) for i in range(0, len(words), chunk_size)]
    time_per_chunk = total_duration / max(len(chunks), 1)

    def fmt_time(s):
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        sec = s % 60
        return f"{h:02}:{m:02}:{sec:06.3f}".replace('.', ',')

    for idx, chunk in enumerate(chunks):
        start = idx * time_per_chunk
        end = start + time_per_chunk
        srt_lines.append(f"{idx+1}")
        srt_lines.append(f"{fmt_time(start)} --> {fmt_time(end)}")
        srt_lines.append(chunk)
        srt_lines.append("")

    with open('/tmp/subtitles.srt', 'w', encoding='utf-8') as f:
        f.write('\n'.join(srt_lines))

    # Add audio + subtitles to video
    subprocess.run([
        'ffmpeg', '-y',
        '-i', '/tmp/video_raw.mp4',
        '-i', '/tmp/audio.mp3',
        '-vf', "subtitles=/tmp/subtitles.srt:force_style='FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,Bold=1,Alignment=2'",
        '-c:v', 'libx264', '-c:a', 'aac', '-b:a', '192k',
        '-shortest', '/tmp/final_output.mp4'
    ], capture_output=True)

    return send_file('/tmp/final_output.mp4', mimetype='video/mp4')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
