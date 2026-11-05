"""Compose existing approved artwork onto the native wizard's opaque background."""
from pathlib import Path
from PIL import Image,ImageOps
ROOT=Path(__file__).resolve().parents[1]

def build():
    background=Image.open(ROOT/'packaging/exe/assets/welcome.png').convert('RGBA')
    logo=Image.open(ROOT/'packaging/shared/icon-source.png').convert('RGBA')
    logo=ImageOps.contain(logo,(240,240),Image.Resampling.LANCZOS)
    background.alpha_composite(logo,((background.width-logo.width)//2,190))
    wordmark=Image.open(ROOT/'app/icons/wwrecorder.png').convert('RGBA')
    bounds=wordmark.getchannel('A').getbbox()
    if bounds:wordmark=wordmark.crop(bounds)
    wordmark=ImageOps.contain(wordmark,(background.width-100,160),Image.Resampling.LANCZOS)
    background.alpha_composite(wordmark,((background.width-wordmark.width)//2,470))
    background.convert('RGB').save(ROOT/'packaging/exe/assets/branded.png')
    # Header logo is flattened against the wizard surface, avoiding a black alpha box.
    header=Image.new('RGBA',(128,128),'#292929')
    header.alpha_composite(Image.open(ROOT/'packaging/shared/icon-source.png').convert('RGBA').resize((112,112),Image.Resampling.LANCZOS),(8,8))
    header.convert('RGB').save(ROOT/'packaging/exe/assets/header-logo.png')

if __name__=='__main__':build()
