from flask import Flask, request, send_file, jsonify
from gtts import gTTS
import io
import subprocess
import requests
import os
import threading
import uuid
import traceback

app = Flask(__name__)

def save_job(job_id, status):
    with open(f'/tmp/job_{job_id}.txt', 'w') as f:
        f.write(status)

def get_job(job_id):
    try:
        with open(f'/tmp/job_{job_id}.txt', 'r') as f:
            return f.read()
    except:
        return 'not_found'

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
        save_job(job_id, 'processing')

        r_audio = requests.get(audio_url, timeout=30)
        audio_path = f'/tmp/{job_id}_audio.mp3'
        with open(audio_path, 'wb') as f:
            f.write(r_audio.content)

        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
            capture_output=True, text=True
        )
        total_duration = float(result.stdout.strip())
        per_image = total_duration / max(len(image_urls), 1)

        segment_files = []
        for i, url in enumerate(image_urls):
            r = requests.get(url, timeout=30)
            img_path = f'/tmp/{job_id}_img_{i}.jpg'
            with open(img_path, 'wb') as f:
                f.write(r.content)

            out = f'/tmp/{job_id}_seg_{i}.mp4'
            res = subprocess.run([
                'ffmpeg', '-y', '-loop', '1', '-i', img_path,
                '-vf', 'scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720',
                '-t', str(per_image), '-c:v', 'libx264',
                '-pix_fmt', 'yuv420p', '-r', '25', out
            ], capture_output=True, timeout=300)

            if os.path.exists(out) and os.path.getsize(out) > 0:
                segment_files.append(out)
            else:
                save_job(job_id, f'error: segment {i} failed - {res.stderr.decode()}')
                return

        list_file = f'/tmp/{job_id}_list.txt'
        with open(list_file, 'w') as f:
            for s in segment_files:
                f.write(f"file '{s}'\n")

        res = subprocess.run([
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
            '-i', list_file, '-c', 'copy', f'/tmp/{job_id}_raw.mp4'
        ], capture_output=True, timeout=300)

        if not os.path.exists(f'/tmp/{job_id}_raw.mp4'):
            save_job(job_id, f'error: concat failed - {res.stderr.decode()}')
            return

        res = subprocess.run([
            'ffmpeg', '-y',
            '-i', f'/tmp/{job_id}_raw.mp4',
            '-i', audio_path,
            '-c:v', 'libx264', '-c:a', 'aac',
            '-b:a', '192k', '-shortest',
            f'/tmp/{job_id}_final.mp4'
        ], capture_output=True, timeout=300)

        if os.path.exists(f'/tmp/{job_id}_final.mp4') and os.path.getsize(f'/tmp/{job_id}_final.mp4') > 0:
            save_job(job_id, 'done')
        else:
            save_job(job_id, f'error: final failed - {res.stderr.decode()}')

    except Exception as e:
        save_job(job_id, f'error: {traceback.format_exc()}')

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
    status = get_job(job_id)
    return jsonify({'job_id': job_id, 'status': status})

@app.route('/get-video/<job_id>', methods=['GET'])
def get_video(job_id):
    status = get_job(job_id)
    if status == 'done':
        return send_file(f'/tmp/{job_id}_final.mp4', mimetype='video/mp4')
    return jsonify({'error': 'not ready', 'status': status}), 404

@app.route('/debug/<job_id>', methods=['GET'])
def debug(job_id):
    info = {
        'status': get_job(job_id),
        'files': os.listdir('/tmp')
    }
    return jsonify(info)

@app.route('/get-image', methods=['GET'])
def get_image():
    prompt = request.args.get('prompt', 'islamic mosque')
    seed = request.args.get('seed', '1')
    url = f"https://image.pollinations.ai/prompt/{requests.utils.quote(prompt)}?nologo=true&width=1280&height=720&seed={seed}"
    r = requests.get(url, timeout=60)
    return send_file(io.BytesIO(r.content), mimetype='image/jpeg')



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
