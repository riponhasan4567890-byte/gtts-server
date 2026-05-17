from flask import Flask, request, send_file, jsonify
from gtts import gTTS
import io
import subprocess
import requests
import os
import threading
import uuid

app = Flask(__name__)
jobs = {}

@app.route('/tts', methods=['GET'])
def tts():
    text = request.args.get('text', 'hello')
    lang = request.args.get('lang', 'bn')
    tts_obj = gTTS(text=text, lang=lang)
    mp3_fp = io.BytesIO()
    tts_obj.write_to_fp(mp3_fp)
    mp3_fp.seek(0)
    return send_file(mp3_fp, mimetype='audio/mpeg')

def process_video(job_id, image_urls, audio_url, text):
    try:
        jobs[job_id] = 'processing'

        r_audio = requests.get(audio_url)
        with open(f'/tmp/{job_id}_audio.mp3', 'wb') as f:
            f.write(r_audio.content)

        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', f'/tmp/{job_id}_audio.mp3'],
            capture_output=True, text=True
        )
        total_duration = float(result.stdout.strip())
        per_image = total_duration / max(len(image_urls), 1)

        effects = [
            "zoompan=z='min(zoom+0.0015,1.3)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=125:s=1280x720",
            "zoompan=z='if(lte(zoom,1.0),1.3,max(1.001,zoom-0.0015))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=125:s=1280x720",
            "zoompan=z='min(zoom+0.0015,1.3)':x='0':y='ih/2-(ih/zoom/2)':d=125:s=1280x720",
            "zoompan=z='min(zoom+0.0015,1.3)':x='iw-(iw/zoom)':y='ih/2-(ih/zoom/2)':d=125:s=1280x720",
        ]

        segment_files = []
        for i, url in enumerate(image_urls):
            r = requests.get(url, timeout=15)
            img_path = f'/tmp/{job_id}_img_{i}.jpg'
            with open(img_path, 'wb') as f:
                f.write(r.content)

            out = f'/tmp/{job_id}_seg_{i}.mp4'
            effect = effects[i % len(effects)]
            subprocess.run([
                'ffmpeg', '-y', '-loop', '1', '-i', img_path,
                '-vf', f'scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,{effect}',
                '-t', str(per_image), '-c:v', 'libx264',
                '-pix_fmt', 'yuv420p', '-r', '25', out
            ], capture_output=True)
            segment_files.append(out)

        list_file = f'/tmp/{job_id}_list.txt'
        with open(list_file, 'w') as f:
            for s in segment_files:
                f.write(f"file '{s}'\n")

        subprocess.run([
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
            '-i', list_file, '-c', 'copy', f'/tmp/{job_id}_raw.mp4'
        ], capture_output=True)

        words = text.split()
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
            srt_lines += [f"{idx+1}", f"{fmt_time(start)} --> {fmt_time(end)}", chunk, ""]

        with open(f'/tmp/{job_id}.srt', 'w', encoding='utf-8') as f:
            f.write('\n'.join(srt_lines))

        subprocess.run([
            'ffmpeg', '-y',
            '-i', f'/tmp/{job_id}_raw.mp4',
            '-i', f'/tmp/{job_id}_audio.mp3',
            '-vf', f"subtitles=/tmp/{job_id}.srt:force_style='FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,Bold=1,Alignment=2'",
            '-c:v', 'libx264', '-c:a', 'aac', '-b:a', '192k',
            '-shortest', f'/tmp/{job_id}_final.mp4'
        ], capture_output=True)

        jobs[job_id] = 'done'

    except Exception as e:
        jobs[job_id] = f'error: {str(e)}'

@app.route('/create-video', methods=['POST'])
def create_video():
    data = request.get_json()
    job_id = str(uuid.uuid4())[:8]
    thread = threading.Thread(
        target=process_video,
        args=(job_id, data.get('image_urls', []),
              data.get('audio_url', ''), data.get('text', ''))
    )
    thread.start()
    return jsonify({'job_id': job_id, 'status': 'processing'})

@app.route('/video-status/<job_id>', methods=['GET'])
def video_status(job_id):
    status = jobs.get(job_id, 'not_found')
    return jsonify({'job_id': job_id, 'status': status})

@app.route('/get-video/<job_id>', methods=['GET'])
def get_video(job_id):
    if jobs.get(job_id) == 'done':
        return send_file(f'/tmp/{job_id}_final.mp4', mimetype='video/mp4')
    return jsonify({'error': 'not ready'}), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
