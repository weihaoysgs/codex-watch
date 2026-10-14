"""App-authored Qt scene animation, layered with the bundled CC0 character art.

Props and articulated body motion are drawn locally, not downloaded GIFs. The
original character's head is retained; task state remains owned by DesktopPet.
"""
import math
from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import QColor, QPen, QPainterPath, QPolygonF

ACTIVITIES = ('laundry', 'snack', 'chase', 'play', 'jump', 'run', 'walk')
DURATIONS = (14, 12, 12, 12, 5, 6, 5)


def activity_title(action, kind):
    return {'laundry': '认真搓衣服', 'snack': '吃小鱼干' if kind == 'cat' else '啃小骨头',
            'chase': '追小老鼠' if kind == 'cat' else '追小皮球',
            'play': '拨弄毛线球' if kind == 'cat' else '接飞盘',
            'run': '撒欢跑一会', 'walk': '散散步', 'jump': '开心蹦蹦跳',
            'idle': '安静陪着你', 'celebrate': '完成啦，快来看看'}.get(action, action)


def style(p, fill, stroke='#424047', width=1.7):
    p.setBrush(QColor(fill) if fill else Qt.NoBrush)
    p.setPen(QPen(QColor(stroke), width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin) if stroke else Qt.NoPen)


def ellipse(p, x, y, w, h, fill, stroke='#424047', width=1.7):
    style(p, fill, stroke, width)
    p.drawEllipse(QRectF(x, y, w, h))


def curve(p, start, control1, control2, end, color, width):
    path = QPainterPath(QPointF(*start))
    path.cubicTo(QPointF(*control1), QPointF(*control2), QPointF(*end))
    style(p, None, color, width)
    p.drawPath(path)


def fish(p, x, y, angle=0, eaten=False):
    p.save(); p.translate(x, y); p.rotate(angle)
    style(p, '#efc487', '#986c4a', 1.2)
    p.drawPolygon(QPolygonF([QPointF(-10, 0), QPointF(-19, -7), QPointF(-19, 7)]))
    if eaten:
        curve(p, (-11, 0), (-4, 0), (3, 0), (10, 0), '#f5e6ca', 3)
        for x in (-7, -2, 3):
            curve(p, (x-2, -5), (x, -3), (x, 3), (x-2, 5), '#f5e6ca', 2)
    else:
        ellipse(p, -12, -7, 28, 14, '#efc487', '#986c4a', 1.2)
        for x in (-5, 0):
            curve(p, (x, -4), (x-2, -1), (x-2, 1), (x, 4), '#ce985f', 1)
    ellipse(p, 10, -3, 2, 2, '#424047', None)
    p.restore()


def bone(p, x, y, angle=0):
    p.save(); p.translate(x, y); p.rotate(angle)
    style(p, '#fff0ce', '#b99a6b', 1.2)
    p.drawRoundedRect(QRectF(-13, -3, 26, 6), 3, 3)
    for cx in (-14, 14):
        ellipse(p, cx-4, -7, 8, 8, '#fff0ce', '#b99a6b', 1.2)
        ellipse(p, cx-4, -1, 8, 8, '#fff0ce', '#b99a6b', 1.2)
    p.restore()


def ball(p, x, y, t, yarn=False):
    p.save(); p.translate(x, y); p.rotate(t*130)
    ellipse(p, -12, -12, 24, 24, '#d8a8ce' if yarn else '#eaa477', '#956b8e' if yarn else '#b67854')
    for offset in (-6, 0, 6):
        curve(p, (-9, offset-3), (0, offset+8), (3, offset-8), (10, offset+2),
              '#f4d8eb' if yarn else '#ffe9bb', 1.7)
    p.restore()


def mouse(p, x, y, t):
    p.save(); p.translate(x, y)
    curve(p, (-12, 1), (-26, -12+math.sin(t*9)*5), (-28, 9), (-40, -2), '#b28a9c', 2)
    for dx in (-8, 4):
        curve(p, (dx, 3), (dx+2, 5), (dx+math.sin(t*16)*4, 7), (dx+4, 7), '#827988', 2)
    ellipse(p, -16, -9, 28, 16, '#aaa2b6', '#716a7d', 1.3)
    ellipse(p, -2, -16, 12, 12, '#c0b7c9', '#716a7d', 1.3)
    ellipse(p, 1, -13, 6, 6, '#e3b8c5', None)
    ellipse(p, 8, -5, 2, 2, '#38333d', None)
    ellipse(p, 11, -2, 4, 3, '#d5a3b2', None)
    p.restore()


def sprite(p, pet, action, t, x=0, y=0, flip=False, rotation=0):
    frames = pet.frames[action]
    im = frames[int(t*12) % len(frames)]
    p.save(); p.translate(x, y); p.rotate(rotation)
    if flip: p.scale(-1, 1)
    p.drawPixmap(QRectF(-72, -120, 144, 120), im, QRectF(im.rect()))
    p.restore()


def character(p, pet, t, paws=((-22, -27), (22, -27)), nod=0, tilt=0):
    """Articulated body with original head; prevents extra hands from sprite overlays."""
    fur = '#898a88' if pet.kind == 'cat' else '#f5a51e'
    outline = '#30312e'
    curve(p, (-12, -20), (-30, -9), (-39, -32+math.sin(t*3)*5), (-33, -18), outline, 7)
    curve(p, (-12, -20), (-30, -9), (-39, -32+math.sin(t*3)*5), (-33, -18), fur, 4)
    for x, angle in ((-15, -7), (3, 7)):
        p.save(); p.translate(x+6, -10); p.rotate(angle)
        ellipse(p, -6, -7, 12, 18, fur, outline, 1.8)
        ellipse(p, -5, 5, 10, 5, '#e6e5df', None)
        p.restore()
    ellipse(p, -18, -51, 36, 44, fur, outline, 2)
    ellipse(p, -10, -48, 22, 34, '#e8e6df', None)
    for side, target in zip((-1, 1), paws):
        start = (side*14, -43)
        c1, c2 = (side*29, -42), (target[0]+side*5, target[1]+7)
        curve(p, start, c1, c2, target, outline, 10)
        curve(p, start, c1, c2, target, fur, 6.5)
        ellipse(p, target[0]-4, target[1]-3, 8, 7, '#e6e5df', outline, 1)
    # The 288x240 source head ends at row 148 in the normalized CC0 atlas.
    im = pet.frames['idle'][int(t*5) % len(pet.frames['idle'])]
    p.save(); p.translate(0, -46+nod); p.rotate(tilt)
    p.drawPixmap(QRectF(-72, -74, 144, 74), im, QRectF(0, 0, 288, 148))
    p.restore()


def laundry(p, pet, t):
    beat = math.sin(t*7)
    # A drying rack grounds the activity, with a second little towel swaying.
    style(p, None, '#ac9888', 3)
    p.drawLine(QPointF(49, 7), QPointF(49, -72))
    p.drawLine(QPointF(105, 7), QPointF(105, -72))
    p.drawLine(QPointF(45, -71), QPointF(109, -71))
    cloth = QPainterPath(QPointF(63, -70))
    cloth.lineTo(88, -70); cloth.lineTo(90+math.sin(t)*2, -33)
    cloth.quadTo(76, -29, 61, -34); cloth.closeSubpath()
    style(p, '#eec3c3', '#bf959c', 1.4); p.drawPath(cloth)
    p.save(); p.translate(-18, 0)
    character(p, pet, t, ((-12, -29+beat*5), (17, -29-beat*5)), nod=beat*1.2, tilt=beat*2)
    ellipse(p, -45, -31, 90, 25, '#dbf3f2', '#8bbabc')
    cloth = QPainterPath(QPointF(-19, -34+beat*4))
    cloth.cubicTo(-9, -45, 9, -27, 22, -35-beat*4)
    cloth.lineTo(20, -17); cloth.quadTo(0, -9, -21, -18); cloth.closeSubpath()
    style(p, '#aab4e6', '#7787bb', 1.4); p.drawPath(cloth)
    for x, y in ((-12, -34+beat*4), (18, -34-beat*4)):
        ellipse(p, x-5, y-3, 11, 8, '#e7e4dc', '#42423c', 1.2)
    tub = QPainterPath(QPointF(-45, -20)); tub.lineTo(-35, 9)
    tub.quadTo(0, 19, 35, 9); tub.lineTo(45, -20); tub.quadTo(0, -7, -45, -20)
    style(p, '#a9d4d6', '#79a6ac', 1.6); p.drawPath(tub)
    curve(p, (-33, -8), (-15, -3), (15, -3), (33, -8), '#d7eeee', 2)
    for i in range(7):
        ellipse(p, -35+i*10, -25+math.sin(t*3+i)*2, 9, 7, '#f0ffff', '#c7e5e5', .8)
    for i in range(3):
        phase = (t*1.3+i*.3) % 1
        ellipse(p, -44+i*38+math.sin(t+i)*3, -32-phase*22, 4+phase*3, 4+phase*3,
                '#e8f9fa', '#afdbdf', .7)
    p.restore()


def snack(p, pet, t):
    phase = t % 5
    # Reach down, lift to mouth, chew, then lower. Food follows the paws.
    lift = min(1, max(0, phase/.9)) if phase < 3.8 else max(0, (5-phase)/1.2)
    y = -12 - lift*42
    chew = math.sin(t*18) if 1 < phase < 3.8 else 0
    character(p, pet, t, ((-13, y+9), (16, y+9)), nod=chew*.8+(1-lift)*3, tilt=(1-lift)*7)
    ellipse(p, -37, 4, 75, 14, '#f2e5d6', '#c5b3a3', 1.4)
    ellipse(p, -31, 6, 63, 7, '#e4cdb7', None)
    food = fish if pet.kind == 'cat' else bone
    food(p, -17, 7, -12)
    food(p, 17, 7, 15)
    if pet.kind == 'cat':
        fish(p, 5, y+chew, chew*5, eaten=phase>2.9)
    else:
        bone(p, 5, y+chew, chew*8)
    if 1 < phase < 3.8:
        for i in range(3):
            u = (t*3+i*.27) % 1
            ellipse(p, 8+i*5, -48+u*24, 2, 2, '#d6b27d', None)


def chase(p, pet, t, roam):
    # Offset, smooth paths let the prey lead, turn, and escape the pounce.
    phase = t*1.1
    x = math.sin(phase)*60 if roam else -38
    prey = math.sin(phase+.65)*110 if roam else 42+math.sin(t*3)*17
    leap = max(0, math.sin(phase*2))**6
    p.save(); p.translate(prey, 0)
    if roam and math.cos(phase+.65)<0: p.scale(-1, 1)
    if pet.kind == 'cat': mouse(p, 0, -3, t)
    else: ball(p, 0, -7-abs(math.sin(t*7))*9, t)
    p.restore()
    sprite(p, pet, 'jump' if leap>.15 else 'run', t, x, -leap*26,
           flip=roam and math.cos(phase)<0, rotation=leap*8)


def play(p, pet, t):
    phase = t % 4
    if pet.kind == 'cat':
        reach = max(0, math.sin(t*2))
        character(p, pet, t, ((-22, -26), (23+reach*15, -21+reach*10)), tilt=reach*5)
        x = 48+math.sin(t*2-1)*22
        curve(p, (x, 3), (x-18, 10), (x-35, -6), (x-42, 6), '#ba91b0', 1.4)
        ball(p, x, -5, t, yarn=True)
    else:
        u = phase/4
        jump = max(0, math.sin((u-.35)*math.pi*2))*23
        sprite(p, pet, 'jump', t, y=-jump)
        if u < .6:
            v = u/.6
            x, y = 100-90*v, -40*(1-v)+(-53-jump)*v-45*math.sin(v*math.pi)
        elif u < .83:
            x, y = 10, -53-jump
        else:
            v = (u-.83)/.17
            x, y = 10+90*v, (-53-jump)*(1-v)-40*v-25*math.sin(v*math.pi)
        p.save(); p.translate(x, y); p.rotate(math.sin(t*5)*17 if u<.6 or u>.83 else 0)
        ellipse(p, -23, -5, 46, 10, '#a4c5bb', '#6e9c8f', 1.5)
        ellipse(p, -16, -3, 32, 5, '#d8e8d6', '#8eb6a8', 1)
        p.restore()


def draw_scene(p, pet, action, t, roam=True):
    if action == 'laundry': laundry(p, pet, t)
    elif action == 'snack': snack(p, pet, t)
    elif action == 'chase': chase(p, pet, t, roam)
    elif action == 'play': play(p, pet, t)
    elif action in ('jump', 'celebrate'):
        sprite(p, pet, 'jump', t, y=-24*abs(math.sin(t*math.pi)))
    elif action in ('walk', 'run'):
        x = math.sin(t*.65)*65 if roam else 0
        sprite(p, pet, action, t, x=x, flip=roam and math.cos(t*.65)<0)
    else: sprite(p, pet, 'idle', t)
