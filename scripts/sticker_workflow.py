"""Offline sticker project workflow. Python 3.10+, Pillow. Never calls an image API."""
import argparse
from collections import deque
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import sys
import zipfile
from PIL import Image, ImageDraw, ImageFilter, ImageFont, GifImagePlugin
from inspect_gifs import inspect

def check(ok, message):
    if not ok: raise ValueError(message)

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def read(path): return json.loads(path.read_text(encoding='utf-8'))

def write(path, data, replace=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if replace:
        temp=path.with_suffix(path.suffix+'.tmp')
        with temp.open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2)
        temp.replace(path)
    else:
        with path.open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2)

def identifier(value):
    check(re.fullmatch(r'[A-Za-z0-9_-]+',value),'Use letters/numbers/hyphen/underscore for IDs')
    return value

def font(path, size):
    return ImageFont.truetype(str(path),size) if path else ImageFont.load_default()

def fit(image, size):
    ratio=min(size[0]/image.width,size[1]/image.height)
    return resize(image,(max(1,round(image.width*ratio)),max(1,round(image.height*ratio))))

def resize(image,size):
    # Premultiplied alpha avoids background RGB leaking into partially transparent edges.
    return image.convert('RGBA').convert('RGBa').resize(size,Image.Resampling.LANCZOS).convert('RGBA')

def init(root,master,references,font_path):
    check(not root.exists(),'Choose a new project directory')
    refs=[]
    for p in references:
        refs.extend(sorted(x for x in p.rglob('*') if x.suffix.lower()=='.gif')) if p.is_dir() else refs.append(p)
    check(refs,'No references')
    for p in refs:inspect(p)
    Image.open(master).verify()
    if font_path: font(font_path,24)
    root.mkdir(parents=True)
    (root/'sources').mkdir();suffix=master.suffix.lower()
    shutil.copy2(master,root/'sources'/('character'+suffix))
    tasks=[]
    for i,p in enumerate(refs,1):
        tid=f'R{i:03d}';folder=root/'tasks'/tid;folder.mkdir(parents=True)
        shutil.copy2(p,folder/'reference.gif')
        tasks.append({'id':tid,'label':p.stem,'reference':f'tasks/{tid}/reference.gif','reference_sha256':sha(p),'status':'new','selected_revision':None})
    project={'schema_version':1,'character':f'sources/character{suffix}','character_sha256':sha(master),'font':str(font_path.resolve()) if font_path else None,'defaults':{'size':[240,240],'outline_px':3,'max_bytes':500000},'tasks':tasks,'submission':{'state':'not_submitted','official_rules_verified':False},'events':[]}
    write(root/'project.json',project)
    return {'project':str(root),'references':len(tasks),'network_requests':0}

def task_of(project,tid):
    result=next((x for x in project['tasks'] if x['id']==tid),None)
    check(result is not None,'Unknown task');return result

def extract(root, project):
    for task in project['tasks']:
        folder=root/'tasks'/task['id']/'analysis'
        if folder.exists():continue
        source=root/task['reference'];check(sha(source)==task['reference_sha256'],'Reference changed')
        metadata=inspect(source);folder.mkdir()
        fnt=font(project.get('font'),16)
        with Image.open(source) as gif:
            cols=min(6,gif.n_frames);rows=(gif.n_frames+cols-1)//cols
            sheet=Image.new('RGB',(cols*180,rows*210),'#eeeeee');draw=ImageDraw.Draw(sheet)
            for i in range(gif.n_frames):
                gif.seek(i);frame=gif.convert('RGBA');frame.save(folder/f'frame-{i+1:03d}.png')
                small=fit(frame,(164,164));x=(i%cols)*180+8;y=(i//cols)*210+8
                sheet.paste(small,(x+(164-small.width)//2,y+(164-small.height)//2),small)
                draw.text((x,y+168),f'{i+1} / {metadata["durations_ms"][i]}ms',font=fnt,fill='black')
        sheet.save(folder/'contact.png');write(folder/'metadata.json',metadata)
        write(folder/'motion-analysis.json',{'visual_review_complete':False,'emotion':None,'caption':None,'composition':None,'occlusions':None,'route':None,'route_reason':None,'frames':[{'index':i+1,'duration_ms':d,'pose':None,'eyes':None,'hands':None,'prop':None,'text':None,'redraw_needed':None} for i,d in enumerate(metadata['durations_ms'])]})
        # Rendering is deliberately not enabled by an unreviewed motion template.
        write(root/'tasks'/task['id']/'render.json',{'frames':[],'durations_ms':metadata['durations_ms'],'size':[240,240],'union_crop':True,'character_box':[10,54,230,230],'outline_px':3,'alpha_threshold':128,'background_remove':None,'caption':'','font':project.get('font'),'font_size':34,'text_top':6,'text_stroke':2,'max_bytes':500000})
        task['status']='analysis_pending'
    write(root/'project.json',project,True)
    return {'analysis':'Extracted all frames; Codex must visually inspect contact sheets AND playback before proposing routes.'}

def remove_background(image, spec, protect=None):
    if not spec:return image
    color=tuple(spec['rgb']);tolerance=int(spec.get('tolerance',18))
    check(len(color)==3 and all(type(c) is int and 0<=c<=255 for c in color),'Invalid RGB')
    check(0<=tolerance<=255,'Invalid tolerance')
    result=image.copy();pixels=result.load();w,h=result.size
    mask=Image.open(protect).convert('L') if protect else None
    check(mask is None or mask.size==result.size,'Protection mask dimensions differ')
    pm=mask.load() if mask else None
    seen=bytearray(w*h);queue=deque()
    for x in range(w):queue.append((x,0));queue.append((x,h-1))
    for y in range(h):queue.append((0,y));queue.append((w-1,y))
    while queue:
        x,y=queue.popleft();index=y*w+x
        if seen[index]:continue
        seen[index]=1
        if pm and pm[x,y]>0:continue
        r,g,b,a=pixels[x,y]
        if a and max(abs(r-color[0]),abs(g-color[1]),abs(b-color[2]))>tolerance:continue
        pixels[x,y]=(r,g,b,0)
        if x:queue.append((x-1,y))
        if x+1<w:queue.append((x+1,y))
        if y:queue.append((x,y-1))
        if y+1<h:queue.append((x,y+1))
    return result

def encode_gif(frames,durations,path,threshold):
    # One palette across the sequence; index 255 is reserved exclusively for transparency.
    check(1<=threshold<=255,'Alpha threshold must be 1..255')
    samples=[]
    for image in frames:
        small=image.copy();small.thumbnail((96,96));samples.append(small)
    atlas=Image.new('RGB',(96,96*len(samples)),'white')
    for i,s in enumerate(samples):
        bg=Image.new('RGBA',s.size,'white');bg.alpha_composite(s);atlas.paste(bg.convert('RGB'),(0,i*96))
    palette=atlas.quantize(colors=255,method=Image.Quantize.MEDIANCUT)
    pal=palette.getpalette()[:765]+[0,0,0]
    # A duplicate final color prevents opaque pixels getting quantized to transparent black.
    pal[765:768]=pal[762:765];palette.putpalette(pal)
    encoded=[]
    for image in frames:
        bg=Image.new('RGBA',image.size,'white');bg.alpha_composite(image)
        indexed=bg.convert('RGB').quantize(palette=palette,dither=Image.Dither.NONE)
        data=bytearray(indexed.tobytes());alpha=image.getchannel('A').tobytes()
        for i,a in enumerate(alpha):
            if a<threshold:data[i]=255
            elif data[i]==255:data[i]=254
        indexed.frombytes(bytes(data));indexed.putpalette(pal);indexed.info['transparency']=255;encoded.append(indexed)
    with path.open('xb') as output:
        for block in GifImagePlugin._get_global_header(encoded[0],{'loop':0,'transparency':255}):output.write(block)
        for image,ms in zip(encoded,durations):
            GifImagePlugin._write_frame_data(output,image,(0,0),{'duration':ms,'disposal':2,'transparency':255,'include_color_table':False})
        output.write(b';')

def render(root,project,tid,revision):
    task=task_of(project,tid);identifier(revision)
    base=root/'tasks'/tid;cfg=read(base/'render.json')
    check(cfg['frames'],'Set frames in render.json; no generation is performed by this command')
    source=root/task['reference'];check(sha(source)==task['reference_sha256'],'Reference changed')
    ref=inspect(source);durations=cfg['durations_ms']
    check(durations==ref['durations_ms'],'Reference timing must match exactly; do not change it silently')
    check(len(cfg['frames'])==len(durations),'One frame path for each reference time slot required')
    check(all(type(d) is int and d>0 and d%10==0 for d in durations),'GIF durations must be positive 10ms units')
    size=tuple(cfg.get('size',[240,240]));check(size==(240,240),'This exporter targets 240x240')
    paths=[(base/p).resolve() for p in cfg['frames']]
    check(not cfg.get('protection_masks') or len(cfg['protection_masks'])==len(paths),'One protection mask per frame required')
    frames=[]
    for i,p in enumerate(paths):
        image=Image.open(p).convert('RGBA')
        floor=int(cfg.get('source_alpha_floor',0))
        check(0<=floor<=255,'Invalid source alpha floor')
        if floor:image.putalpha(image.getchannel('A').point(lambda a:0 if a<floor else a))
        masks=cfg.get('protection_masks',[])
        protection=(base/masks[i]) if masks else None
        frames.append(remove_background(image,cfg.get('background_remove'),protection))
    check(len({f.size for f in frames})==1,'Normalize source canvases first, without per-frame tight cropping')
    bounds=[f.getbbox() for f in frames if f.getbbox()]
    check(bounds,'All frames empty')
    union=(min(b[0] for b in bounds),min(b[1] for b in bounds),max(b[2] for b in bounds),max(b[3] for b in bounds)) if cfg.get('union_crop',True) else (0,0,*frames[0].size)
    left,top,right,bottom=cfg['character_box'];check(0<=left<right<=240 and 0<=top<bottom<=240,'Invalid character box')
    outline=float(cfg.get('outline_px',3));check(0<=outline<=12,'Outline range is 0..12px')
    space=outline+1
    factor=min((right-left-2*space)/(union[2]-union[0]),(bottom-top-2*space)/(union[3]-union[1]))
    check(factor>0,'Character box too small')
    # 4x canvas, shared crop, scale and anchor for ALL frames; bottom anchored.
    hi=4;tw=max(1,round((union[2]-union[0])*factor*hi));th=max(1,round((union[3]-union[1])*factor*hi))
    x=round((left+right)*hi/2-tw/2);y=round((bottom-space)*hi-th)
    caption=cfg.get('caption','');fp=cfg.get('font') or project.get('font')
    check(not caption or fp,'A local font is required for caption text')
    fnt=font(fp,round(cfg.get('font_size',34)*hi)) if caption else None
    output_frames=[];diagnostic=[];text_box=None
    if caption:
        bbox=fnt.getbbox(caption);width=bbox[2]-bbox[0];height=bbox[3]-bbox[1];stroke=round(cfg.get('text_stroke',2)*hi)
        check(width+2*stroke<=240*hi,'Caption too wide; adjust font size explicitly')
        text_box=[(240*hi-width)//2,round(cfg.get('text_top',6)*hi),width,height]
        check(text_box[1]+height+stroke<top*hi,'Text overlaps reserved character area')
    for i,frame in enumerate(frames):
        crop=resize(frame.crop(union),(tw,th));layer=Image.new('RGBA',(240*hi,240*hi));layer.alpha_composite(crop,(x,y))
        if outline:
            radius=max(1,round(outline*hi));expanded=layer.getchannel('A').filter(ImageFilter.MaxFilter(2*radius+1))
            backing=Image.new('RGBA',layer.size,'white');backing.putalpha(expanded);backing.alpha_composite(layer);layer=backing
        if caption:
            tx,ty,_,_=text_box;bb=fnt.getbbox(caption)
            ImageDraw.Draw(layer).text((tx-bb[0],ty-bb[1]),caption,font=fnt,fill='#242424',stroke_width=stroke,stroke_fill='white')
        output_frames.append(resize(layer,size))
    folder=base/'revisions'/revision;check(not folder.exists(),'Revision exists; choose a new name');folder.mkdir(parents=True)
    (folder/'frames').mkdir()
    for i,frame in enumerate(output_frames):frame.save(folder/'frames'/f'{i+1:03d}.png')
    gif=folder/'sticker.gif';encode_gif(output_frames,durations,gif,int(cfg.get('alpha_threshold',128)))
    actual=inspect(gif)
    check(actual['durations_ms']==durations and actual['frame_count']==len(frames),'Encoded GIF lost frame slots/timing')
    preview=Image.new('RGB',(480,240))
    for i,bg in enumerate(('#fafafa','#202124')):
        tile=Image.new('RGBA',(240,240),bg);tile.alpha_composite(output_frames[0]);preview.paste(tile.convert('RGB'),(i*240,0))
    preview.save(folder/'light-dark-preview.png')
    # Diagnostic APNG may merge identical frames; it is not the platform deliverable.
    if len(output_frames)>1:output_frames[0].save(folder/'alpha-diagnostic.png',save_all=True,append_images=output_frames[1:],duration=durations,loop=0,format='PNG')
    else:output_frames[0].save(folder/'alpha-diagnostic.png')
    result={'gif':str(gif.relative_to(root)).replace('\\','/'),'sha256':sha(gif),'source_inputs':[{'file':str(p),'sha256':sha(p)} for p in paths],'reference_sha256':sha(source),'render_config':cfg,'union_bbox':union,'shared_scale':factor,'shared_position_hi':[x,y],'outline_px_at_240':outline,'technical_pass':actual['bytes']<=cfg.get('max_bytes',500000) and actual['infinite_loop'] and all(f['transparent_pixels']>0 for f in actual['frames']),'actual':actual,'visual_review':'pending','user_review':'pending'}
    write(folder/'validation.json',result);task['selected_revision']=revision;task['status']='pending_review'
    write(root/'project.json',project,True)
    return {'revision':revision,'technical_pass':result['technical_pass'],'bytes':actual['bytes'],'frames':len(frames),'visual_review':'pending'}

def approval(root,project,tid,decision,note):
    task=task_of(project,tid);check(note.strip(),'Record actual user decision text')
    if decision=='approved':
        check(task.get('selected_revision'),'No selected revision')
        report=read(root/'tasks'/tid/'revisions'/task['selected_revision']/'validation.json')
        check(report['technical_pass'],'Cannot approve a technical failure through this command')
        check(sha(root/report['gif'])==report['sha256'],'GIF changed after validation')
    task['status']=decision
    project['events'].append({'utc':datetime.now(timezone.utc).isoformat(),'task':tid,'revision':task.get('selected_revision'),'decision':decision,'user_instruction':note,'gif_sha256':report['sha256'] if decision=='approved' else None})
    write(root/'project.json',project,True)
    return {'task':tid,'status':decision}

def import_gif(root,project,tid,source,name):
    task=task_of(project,tid);identifier(name)
    ref=inspect(root/task['reference']);actual=inspect(source)
    check(actual['frame_count']==ref['frame_count'] and actual['durations_ms']==ref['durations_ms'],'Generated GIF timing differs; inspect and plan local correction first, do not silently retime')
    folder=root/'tasks'/tid/'inputs'/name;check(not folder.exists(),'Import exists');folder.mkdir(parents=True)
    shutil.copy2(source,folder/'original.gif');paths=[]
    with Image.open(source) as image:
        for i in range(image.n_frames):
            image.seek(i);p=folder/f'{i+1:03d}.png';image.convert('RGBA').save(p)
            paths.append(p.relative_to(root/'tasks'/tid).as_posix())
    write(folder/'source.json',{'sha256':sha(source),'actual':actual})
    cfg_path=root/'tasks'/tid/'render.json';cfg=read(cfg_path)
    # Preserve prior render configuration as history before changing the input mapping.
    write(folder/'previous-render.json',cfg)
    cfg['frames']=paths;write(cfg_path,cfg,True)
    return {'imported_frames':len(paths),'source_preserved':True,'network_requests':0}

def review(root,project):
    cards=[]
    for task in project['tasks']:
        tid=task['id'];analysis=root/'tasks'/tid/'analysis';parts=[]
        if task.get('selected_revision'):
            report=read(root/'tasks'/tid/'revisions'/task['selected_revision']/'validation.json');src=report['gif']
            check(sha(root/src)==report['sha256'],'Selected GIF changed')
            parts.append(f'<div class="stage"><img src="{html.escape(src)}"></div><p>{report["actual"]["frame_count"]}帧 / {report["actual"]["total_ms"]}ms / {report["actual"]["bytes"]}字节</p>')
        parts.append(f'<details><summary>参考GIF / 逐帧联系表</summary><div class="stage"><img src="{task["reference"]}"></div>')
        if (analysis/'contact.png').exists():parts.append(f'<a href="tasks/{tid}/analysis/contact.png">打开完整联系表</a>')
        parts.append('</details>')
        cards.append(f'<article><h2>{tid} {html.escape(task["label"])}</h2><b>{html.escape(task["status"])}</b>'+''.join(parts)+'</article>')
    page='<!doctype html><meta charset="utf-8"><title>表情审核</title><style>body{font:16px system-ui;background:#eee;color:#222;margin:24px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px}article{background:white;padding:18px;border-radius:14px}.stage{background:#fafafa;padding:14px;text-align:center}.dark .stage{background:#202124}.stage img{width:240px;height:240px;object-fit:contain}button{padding:12px;margin-bottom:20px}</style><h1>项目审核</h1><p>状态来自用户审核记录。技术通过不代表视觉或平台通过。</p><button onclick="document.body.classList.toggle(\'dark\')">切换深浅背景</button><main>'+''.join(cards)+'</main>'
    (root/'review.html').write_text(page,encoding='utf-8')
    return {'review':str(root/'review.html')}

def package(root,project,name):
    identifier(name);folder=root/'packages'/name;check(not folder.exists(),'Package exists')
    selected=[t for t in project['tasks'] if t['status']=='approved'];check(selected,'No approved stickers')
    master=root/project['character'];check(sha(master)==project['character_sha256'],'Master changed')
    im=Image.open(master).convert('RGBA');check(im.getbbox(),'Empty master');im=im.crop(im.getbbox())
    folder.mkdir(parents=True);(folder/'表情图').mkdir();records=[]
    for i,task in enumerate(selected,1):
        report=read(root/'tasks'/task['id']/'revisions'/task['selected_revision']/'validation.json');src=root/report['gif']
        check(report['technical_pass'] and sha(src)==report['sha256'],'Invalid selected revision')
        dest=folder/'表情图'/f'{i:02d}.gif';shutil.copy2(src,dest);records.append({'id':task['id'],'label':task['label'],'file':f'表情图/{i:02d}.gif','sha256':sha(dest)})
    # Candidate assets only. Author supplied head crop can replace this draft icon.
    def asset(image,size,padding=0):
        canvas=Image.new('RGBA',size);small=fit(image,(size[0]-padding*2,size[1]-padding*2));canvas.alpha_composite(small,((size[0]-small.width)//2,(size[1]-small.height)//2));return canvas
    asset(im,(240,240),6).save(folder/'封面图.png')
    icon_box=project.get('icon_crop')
    icon=im.crop(icon_box) if icon_box else im
    asset(icon,(50,50),2).save(folder/'聊天面板图标.png')
    banner=Image.new('RGBA',(750,400),'#ffe3b6');small=fit(im,(320,360));banner.alpha_composite(small,((750-small.width)//2,400-small.height-20));banner.convert('RGB').save(folder/'详情页横幅.png',optimize=True)
    listing=project.get('listing',{})
    text='# 微信投稿文案候选\n\n'+ '\n\n'.join(f'{key}：{listing.get(key,"待用户填写")}' for key in ['专辑名称','介绍','作者名','版权信息'])
    text+='\n\n表情顺序：\n'+ '\n'.join(f'{i:02d}. {r["label"]}' for i,r in enumerate(records,1))
    text+='\n\n此包未上传。数量与素材规格须在当前官方投稿页复核。封面、图标、横幅为本地候选稿，需视觉审核；默认图标可能需要用户指定头部裁切。字体与素材权利需另核对。\n'
    (folder/'上架文案.md').write_text(text,encoding='utf-8')
    write(folder/'manifest.json',{'official_rules_verified':False,'count':len(records),'files':records,'source_project_sha256':sha(root/'project.json'),'api_calls':0})
    archive=folder.with_suffix('.zip')
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for p in folder.rglob('*'):
            if p.is_file():z.write(p,p.relative_to(folder))
    return {'candidate_package':str(archive),'count':len(records),'submitted':False}

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('doctor');p.add_argument('--font',type=Path)
    p=sub.add_parser('init');p.add_argument('project',type=Path);p.add_argument('--character',type=Path,required=True);p.add_argument('--references',nargs='+',type=Path,required=True);p.add_argument('--font',type=Path)
    for cmd in ['extract','status','review','render','decision','package','import-gif']:
        p=sub.add_parser(cmd);p.add_argument('project',type=Path)
        if cmd in ['render','decision','import-gif']:p.add_argument('--task',required=True)
        if cmd=='render':p.add_argument('--revision',required=True)
        if cmd=='decision':p.add_argument('--status',choices=['approved','pending_review','cancelled'],required=True);p.add_argument('--user-instruction',required=True)
        if cmd=='package':p.add_argument('--name',required=True)
        if cmd=='import-gif':p.add_argument('--name',required=True);p.add_argument('--source',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='doctor':
        import PIL
        if args.font:font(args.font,24)
        result={'python':sys.version.split()[0],'pillow':PIL.__version__,'font_loadable':bool(args.font),'api_required_for_local':False,'network_requests':0}
    elif args.command=='init':result=init(args.project,args.character,args.references,args.font)
    else:
        root=args.project.resolve();project=read(root/'project.json')
        if args.command=='extract':result=extract(root,project)
        elif args.command=='render':result=render(root,project,args.task,args.revision)
        elif args.command=='decision':result=approval(root,project,args.task,args.status,args.user_instruction)
        elif args.command=='review':result=review(root,project)
        elif args.command=='package':result=package(root,project,args.name)
        elif args.command=='import-gif':result=import_gif(root,project,args.task,args.source,args.name)
        else:result=project
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
