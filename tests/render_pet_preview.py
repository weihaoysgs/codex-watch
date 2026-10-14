"""Render real Qt widgets with isolated demo data; never accesses live sessions."""
import io
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'native'))
import main
from PyQt5.QtCore import QByteArray, QBuffer, QIODevice
from PyQt5.QtWidgets import QApplication
from pet_scenes import ACTIVITIES, DURATIONS


def snapshot(widget):
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    widget.grab().save(buf, 'PNG')
    return Image.open(io.BytesIO(bytes(data))).convert('RGBA')


def run():
    with tempfile.TemporaryDirectory() as temp:
        main.DATA = Path(temp)
        app = QApplication([])
        window = main.Window(demo=True)
        window.pet.show()
        work = main.Session('preview', title='桌面宠物功能已准备好，来看看吧', cwd='/Projects/companion',
                            status='running', tracked=True, turn_id='preview')
        window.pet.sync([work])
        font = ImageFont.truetype('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', 19)
        small = ImageFont.truetype('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', 14)
        frames = []
        for i in range(90):
            im = Image.new('RGB', (640, 350), '#f1f2f7')
            draw = ImageDraw.Draw(im)
            draw.text((32, 18), '候响 · 忙碌时，陪你一起动起来', font=font, fill='#343746')
            for x, kind, title in ((0, 'cat', '小猫'), (320, 'dog', '小狗')):
                window.pet.load(kind)
                window.pet.fixed_time = i * sum(DURATIONS)/90 + .3
                pet = snapshot(window.pet)
                im.paste(pet, (x, 65), pet)
                draw.text((x+145, 313), title, font=small, fill='#747a91')
            frames.append(im)
        out = main.ROOT / 'doc'
        frames[0].save(out / 'pets-preview.png')
        frames[0].save(out / 'pets-preview.gif', save_all=True, append_images=frames[1:], duration=200, loop=0)
        gallery = []
        for i in range(48):
            im = Image.new('RGB', (1280, 560), '#f1f2f7')
            draw = ImageDraw.Draw(im)
            draw.text((32, 12), '候响 · 宠物日常  /  猫咪与小狗 · 实际渲染预览', font=font, fill='#343746')
            for row, kind in enumerate(('cat', 'dog')):
                window.pet.load(kind)
                for col, action in enumerate(ACTIVITIES[:4]):
                    window.pet.fixed_time = sum(DURATIONS[:col]) + .2 + i*.12
                    pet = snapshot(window.pet)
                    im.paste(pet, (col*320, 45+row*254), pet)
            gallery.append(im)
        gallery[12].save(out / 'pet-activities.png')
        gallery[0].save(out / 'pet-activities.gif', save_all=True, append_images=gallery[1:], duration=120, loop=0)
        window.pet.load('cat')
        window.pet.fixed_time = 2
        work.status, work.unread = 'completed', True
        window.pet.sync([work])
        window.reminder.update_pending([work], reveal=True)
        app.processEvents()
        bubble = snapshot(window.reminder)
        pet = snapshot(window.pet)
        im = Image.new('RGB', (520, bubble.height+pet.height+95), '#f1f2f7')
        draw = ImageDraw.Draw(im)
        draw.text((32, 16), '工作完成 · 文字提醒，默认静音', font=font, fill='#343746')
        im.paste(bubble, (50, 60), bubble)
        im.paste(pet, ((520-pet.width)//2, bubble.height+72), pet)
        im.save(out / 'pet-bubble-preview.png')
        window.close()


if __name__ == '__main__':
    run()
