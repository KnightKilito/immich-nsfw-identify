"""Render code-native geometric favicon fallbacks. Requires Pillow."""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[1]
SIZE=512
SCALE=SIZE/64


def points(values):
    return [(round(x*SCALE),round(y*SCALE)) for x,y in values]


def create():
    image=Image.new('RGBA',(SIZE,SIZE),(0,0,0,0))
    draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((0,0,SIZE-1,SIZE-1),radius=round(15*SCALE),fill='#1a2b22')
    draw.rounded_rectangle(tuple(round(x*SCALE) for x in (10,13,47,44)),radius=round(6*SCALE),fill='#192b22',outline='#bad8aa',width=round(3*SCALE))
    draw.ellipse(tuple(round(x*SCALE) for x in (17,19,25,27)),fill='#ebca89')
    draw.line(points([(13,39),(24,28),(31,35),(37,29),(44,38)]),fill='#bad8aa',width=round(3.5*SCALE),joint='curve')
    shield=points([(44,29),(56,34),(56,43),(54,48),(50,53),(44,58),(38,55),(34,50),(32,43),(32,34)])
    draw.polygon(shield,fill='#a6ce98',outline='#101714',width=round(2.5*SCALE))
    draw.line(points([(38.5,43),(42.5,47),(49.5,39)]),fill='#193828',width=round(3.6*SCALE),joint='curve')
    for filename,size in [('favicon-32.png',32),('apple-touch-icon.png',180)]:
        image.resize((size,size),Image.Resampling.LANCZOS).save(ROOT/'static'/filename)
    image.save(ROOT/'static'/'favicon.ico',format='ICO',sizes=[(16,16),(32,32),(48,48),(64,64)])
    print('Generated PNG and ICO favicon fallbacks.')


if __name__=='__main__':create()
