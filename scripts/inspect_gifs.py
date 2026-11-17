"""Offline GIF metadata audit. Requires Pillow. Does not modify input files."""
import argparse
import hashlib
import json
from pathlib import Path
from PIL import Image

def inspect(path):
    with Image.open(path) as im:
        if im.format != 'GIF':
            raise ValueError('Input is not GIF')
        size=list(im.size)
        loop=im.info.get('loop')
        frames=[]
        for i in range(im.n_frames):
            im.seek(i)
            rgba=im.convert('RGBA')
            alpha=rgba.getchannel('A')
            frames.append(dict(index=i+1,duration_ms=im.info.get('duration'),
                transparent_pixels=alpha.histogram()[0],bbox=alpha.getbbox(),
                decoded_rgba_colors=len(rgba.getcolors(size[0]*size[1]+1) or [])))
    durations=[f['duration_ms'] for f in frames]
    return dict(file=str(path.resolve()),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        bytes=path.stat().st_size,size=size,frame_count=len(frames),loop=loop,
        infinite_loop=loop==0,durations_ms=durations,
        total_ms=sum(durations) if all(d is not None for d in durations) else None,
        union_bbox=union([f['bbox'] for f in frames]),frames=frames)

def union(boxes):
    boxes=[b for b in boxes if b]
    return [min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)] if boxes else None

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('inputs',nargs='+',type=Path)
    p.add_argument('--output',required=True,type=Path)
    args=p.parse_args()
    if args.output.exists():p.error('Output exists; choose a new report path')
    paths=[]
    for item in args.inputs:
        if item.is_dir():paths.extend(x for x in item.rglob('*') if x.is_file() and x.suffix.lower()=='.gif')
        elif item.is_file():paths.append(item)
        else:p.error(f'Input does not exist: {item}')
    paths=sorted(set(x.resolve() for x in paths))
    if not paths:p.error('No GIF inputs found')
    records=[]
    for path in paths:
        try:records.append(inspect(path))
        except Exception as e:records.append({'file':str(path),'error':str(e)})
    args.output.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive create prevents accidental replacement, including concurrent runs.
    with args.output.open('x',encoding='utf-8') as f:
        json.dump({'offline':True,'files':records},f,ensure_ascii=False,indent=2)
    print(f'Inspected {len(records)} file(s); errors: {sum("error" in r for r in records)}')
    if any('error' in r for r in records):raise SystemExit(1)

if __name__=='__main__':main()
