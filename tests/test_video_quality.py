"""Exercise real two-stage encoding on text and motion, independent of Windows capture."""
import ast,shutil,subprocess
from pathlib import Path
import numpy as np
import pytest
from PIL import Image,ImageDraw,ImageFont


def test_moderate_two_stage_quality_improves_text_without_extreme_size(tmp_path):
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:
        bundled = Path(__file__).resolve().parents[1] / 'app/ffmpeg.exe'
        ffmpeg = str(bundled)
    if not Path(ffmpeg).is_file():pytest.skip('FFmpeg is unavailable')
    tree=ast.parse((Path(__file__).resolve().parents[1]/'app/recorder.py').read_text())
    values={node.targets[0].id:ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in ('TEMP_VIDEO_CRF','FINAL_VIDEO_CRF')}
    width,height,count=640,360,18
    try:font=ImageFont.truetype('DejaVuSans.ttf',16)
    except OSError:font=ImageFont.load_default()
    frames=[]
    for index in range(count):
        image=Image.new('RGB',(width,height),'#f8f8fc');draw=ImageDraw.Draw(image)
        for line in range(12):draw.text((12,10+line*25),f'Screen text 0123456789 — frame {index:02d} / line {line}',font=font,fill='#17213a')
        draw.rectangle((450+index*4,40,475+index*4,100),fill='#ce3650')
        frames.append(np.asarray(image))
    raw=np.stack(frames);source=tmp_path/'screen.rgb';source.write_bytes(raw.tobytes())
    def run(args):
        result=subprocess.run([ffmpeg,'-v','error','-y',*args],capture_output=True,timeout=45)
        assert result.returncode==0,result.stderr.decode(errors='replace')
        return result.stdout
    def encode(label,temp_crf,final_crf):
        intermediate=tmp_path/f'{label}-temp.mkv';final=tmp_path/f'{label}.mkv'
        run(['-f','rawvideo','-pix_fmt','rgb24','-s',f'{width}x{height}','-r','30','-i',str(source),'-c:v','libx264','-preset','ultrafast','-crf',str(temp_crf),'-pix_fmt','yuv420p',str(intermediate)])
        run(['-i',str(intermediate),'-c:v','libx264','-preset','veryfast','-crf',str(final_crf),'-pix_fmt','yuv420p',str(final)])
        decoded=run(['-i',str(final),'-f','rawvideo','-pix_fmt','rgb24','pipe:1'])
        pixels=np.frombuffer(decoded,np.uint8).reshape(count,height,width,3)
        error=np.mean((pixels.astype(np.float32)-raw.astype(np.float32))**2)
        return error,final.stat().st_size
    old_error,old_size=encode('old',23,28)
    error,size=encode('new',values['TEMP_VIDEO_CRF'],values['FINAL_VIDEO_CRF'])
    assert error<old_error
    assert size<old_size*2.5
