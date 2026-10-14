#!/usr/bin/python3
"""Offline deterministic conversion of pzUH's CC0 CatnDog.zip. Build-only Pillow."""
import hashlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA256 = 'e60f863e5abdce6fcded54f6b82bbda752ba0b555bc69c76c7da42d692e7b47c'


def main(source):
    data = Path(source).read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError('Unexpected source archive; review provenance before importing')
    target = ROOT / 'native/assets/pets'
    target.mkdir(parents=True, exist_ok=True)
    manifest = {'source_sha256': SOURCE_SHA256, 'license': 'CC0-1.0', 'pets': {}}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for kind in ('cat', 'dog'):
            sequences = {}
            for action in ('idle', 'walk', 'run', 'jump'):
                names = [n for n in archive.namelist() if n.startswith(f'png/{kind}/{action.title()} (') and n.endswith('.png')]
                names.sort(key=lambda n: int(re.search(r'\((\d+)\)', n)[1]))
                sequences[action] = [Image.open(io.BytesIO(archive.read(n))).convert('RGBA') for n in names]
            # One common crop/scale across every frame, never per-frame cropping that jitters.
            bounds = [im.getbbox() for seq in sequences.values() for im in seq]
            box = (min(b[0] for b in bounds), min(b[1] for b in bounds),
                   max(b[2] for b in bounds), max(b[3] for b in bounds))
            scale = min(280 / (box[2]-box[0]), 232 / (box[3]-box[1]))
            size = (round((box[2]-box[0])*scale), round((box[3]-box[1])*scale))
            animations = {}
            for action, seq in sequences.items():
                atlas = Image.new('RGBA', (288*len(seq), 240))
                for i, im in enumerate(seq):
                    frame = im.crop(box).resize(size, Image.LANCZOS)
                    atlas.alpha_composite(frame, (i*288 + (288-size[0])//2, 236-size[1]))
                name = f'{kind}-{action}.png'
                atlas.save(target / name, optimize=True)
                animations[action] = {'file': name, 'cell': [288, 240], 'frames': len(seq)}
            manifest['pets'][kind] = {'animations': animations}
    (target / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Prepared cat and dog: idle, walk, run, jump')


if __name__ == '__main__':
    main(sys.argv[1])
