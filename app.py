from flask import Flask, request, send_file, jsonify
from gtts import gTTS
import io
import subprocess
import requests
import os

app = Flask(__name__)

@app.route('/tts', methods=['GET'])
def tts():
    text = request.args.get('text', 'hello')
    lang = request.args.get('lang', 'bn')
    tts = gTTS(text=text, lang=lang)
    mp3_fp = io.BytesIO()
    tts.write_to_fp(mp3_fp)
    mp3_fp.seek(0)
    return send_file(mp3_fp, mimetype='audio/mpeg')

@app.route('/create-video', methods=['GET'])
def create_video():
    image_url = request.args.get('image_url')
    audio_url = request.args.get('audio_url')
    
    r_img = requests.get(image_url)
    with open('/tmp/image.jpg', 'wb') as f:
        f.write(r_img.content)
    
    r_audio = requests.get(audio_url)
    with open('/tmp/audio.mp3', 'wb') as f:
        f.write(r_audio.content)
    
    subprocess.run([
        'ffmpeg', '-loop', '1', '-i', '/tmp/image.jpg',
        '-i', '/tmp/audio.mp3', '-c:v', 'libx264',
        '-tune', 'stillimage', '-c:a', 'aac',
        '-b:a', '192k', '-pix_fmt', 'yuv420p',
        '-shortest', '/tmp/output.mp4', '-y'
    ])
    
    return send_file('/tmp/output.mp4', mimetype='video/mp4')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
