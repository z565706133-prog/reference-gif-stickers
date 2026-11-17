"""Portable Images Edits runner: offline default, one explicit request, no retry."""
import argparse
import base64
import hashlib
import io
import json
import math
import os
import re
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ENDPOINT = 'https://api.openai.com/v1/images/edits'

def save(path, data):
    with path.open('x', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def now():
    return datetime.now(timezone.utc).isoformat()

def require(condition, message):
    if not condition:
        raise ValueError(message)

def load_plan(path):
    from PIL import Image
    config = json.loads(path.read_text(encoding='utf-8'))
    require(config.get('schema_version') == 1, 'Unsupported schema')
    require(type(config.get('total_cap')) is int and config['total_cap'] > 0, 'Invalid total cap')
    require(config.get('parameters_verified') is True and config.get('verification_source') and config.get('verified_on'), 'Verify official parameters before preparing this plan')
    require(re.fullmatch(r'[A-Za-z0-9_-]+', config.get('batch_id', '')), 'Invalid batch id')
    require(config.get('jobs'), 'No jobs')
    ids = set()
    snapshot = dict(config)
    snapshot['jobs'] = []
    for job in config['jobs']:
        jid = job.get('id', '')
        require(re.fullmatch(r'[A-Za-z0-9_-]+', jid) and jid not in ids, 'Invalid/duplicate job id')
        ids.add(jid)
        require(type(job.get('cap')) is int and job['cap'] > 0, 'Invalid job cap')
        fields = job['fields']
        allowed = {'model','size','quality','complexity','background','output_format','n','frame_count','frame_duration_ms'}
        require(set(fields) <= allowed, 'Unsupported field; review implementation before extending')
        require(isinstance(fields.get('model'), str) and fields['model'], 'Model required')
        require(fields.get('n') == 1 and type(fields['n']) is int, 'Exactly one image per request')
        require(fields.get('output_format') in ('png', 'gif'), 'Only PNG/GIF output supported')
        require(fields.get('background') in ('auto','transparent','opaque'), 'Explicit background required')
        require(fields.get('size') and fields.get('quality'), 'Size/quality required')
        require(fields['quality'] in ('low','medium','high','auto','xhigh','max'), 'Invalid quality')
        if 'complexity' in fields:
            require(fields['complexity'] in ('low','medium','high'), 'Invalid complexity')
        if fields['output_format'] == 'gif':
            require(type(fields.get('frame_count')) is int and 2 <= fields['frame_count'] <= 16, 'GIF frame_count 2..16 required')
            ms = fields.get('frame_duration_ms')
            require(type(ms) is int and 20 <= ms <= 655350 and ms % 10 == 0, 'GIF duration must be a multiple of 10ms')
        else:
            require('frame_count' not in fields and 'frame_duration_ms' not in fields, 'GIF-only parameters in PNG job')
        prompt = (path.parent / job['prompt_file']).read_text(encoding='utf-8')
        require(prompt.strip(), 'Empty prompt')
        inputs = []
        require(job.get('images'), 'Reference image required')
        for rel in job['images']:
            image = (path.parent / rel).resolve()
            raw = image.read_bytes()
            with Image.open(io.BytesIO(raw)) as im:
                require(im.format in ('PNG','JPEG','WEBP'), 'Use still PNG/JPEG/WebP references')
            inputs.append({'path':str(image), 'sha256':digest(raw)})
        snapshot['jobs'].append(dict(id=jid, cap=job['cap'], fields=fields, prompt=prompt, inputs=inputs))
    pricing = config.get('pricing')
    if pricing:
        require(pricing.get('source') and pricing.get('verified_on'), 'Pricing needs source/date')
        for k in ('text_input_per_million','image_input_per_million','output_per_million'):
            require(type(pricing.get(k)) in (int,float) and math.isfinite(pricing[k]) and pricing[k] >= 0, 'Invalid pricing')
    canonical = json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()
    return snapshot, digest(canonical)

def estimate(usage, pricing):
    if not pricing or not isinstance(usage, dict):
        return None
    details = usage.get('input_tokens_details', {})
    values = [details.get('text_tokens'), details.get('image_tokens'), usage.get('output_tokens')]
    if not all(type(v) is int and v >= 0 for v in values):
        return None
    rates = [pricing[k] for k in ('text_input_per_million','image_input_per_million','output_per_million')]
    return sum(v*r for v,r in zip(values,rates))/1e6

def ledger(state):
    attempts=[]
    for folder in sorted(state.glob('attempt-*')):
        marker=folder/'attempt.json'
        if not marker.exists():
            raise ValueError('Incomplete attempt reservation; stop and inspect, never delete to retry')
        record=json.loads(marker.read_text(encoding='utf-8'))
        result=folder/'result.json'
        record['result']=json.loads(result.read_text(encoding='utf-8')) if result.exists() else {'status':'unknown','estimated_usd':None}
        attempts.append(record)
    return attempts

def run(plan_path, state, mode='dry-run', job_id=None, approval_text=None):
    plan, fingerprint=load_plan(plan_path)
    # Lock for this batch lives next to its plan. The caller cannot reset quota by changing output directories.
    require(state.resolve() == (plan_path.parent / ('runs-'+plan['batch_id'])).resolve(), 'State path mismatch')
    if mode == 'dry-run':
        report={'dry_run':True,'image_requests_sent':0,'plan_sha256':fingerprint,'total_cap':plan['total_cap'],'jobs':plan['jobs'],'pricing':plan.get('pricing'),'estimated_cost_note':'Actual output usage unknown; missing pricing is not zero cost'}
        if state.exists():report['attempts']=ledger(state)
        return report
    state.mkdir(exist_ok=True)
    approval=state/'approval.json'
    if mode == 'approve':
        require(approval_text and approval_text.strip(), 'Record the actual user authorization')
        save(approval,{'plan_sha256':fingerprint,'user_instruction':approval_text,'recorded_utc':now()})
        return {'approved_plan_sha256':fingerprint,'image_requests_sent':0}
    require(approval.exists(), 'No approval. Prepare and obtain user approval first')
    require(json.loads(approval.read_text(encoding='utf-8'))['plan_sha256'] == fingerprint, 'Plan/prompt/reference changed; approval invalid')
    if mode == 'report':
        attempts=ledger(state)
        known=[a['result']['estimated_usd'] for a in attempts if a['result'].get('estimated_usd') is not None]
        return {'attempts_consumed':len(attempts),'total_cap':plan['total_cap'],'known_estimate_usd':sum(known),'unknown_cost_attempts':sum(a['result'].get('estimated_usd') is None for a in attempts),'invoice_verified':False,'attempts':attempts}
    job=next((j for j in plan['jobs'] if j['id']==job_id),None)
    require(job is not None,'Select one known job; automatic batch loops are not provided')
    secret=os.environ.get('OPENAI_API_KEY','').strip()
    require(secret,'Missing local OPENAI_API_KEY; do not paste it into chat')
    # Hold a cross-process lock through reservation and HTTP operation.
    lock=state/'execution.lock'
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    os.close(fd)
    try:
        attempts=ledger(state)
        require(all(a['result']['status']=='success' for a in attempts),'Prior failure or interrupted request: batch stopped; no retry')
        require(len(attempts)<plan['total_cap'],'Total request cap reached')
        require(sum(a['job']==job_id for a in attempts)<job['cap'],'Job request cap reached')
        # The request is fully built from the hash-bound snapshot; changed inputs fail before reservation.
        boundary=uuid.uuid4().hex
        fields=dict(job['fields'],prompt=job['prompt'])
        body=b''.join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k,v in fields.items())
        for i,item in enumerate(job['inputs']):
            raw=Path(item['path']).read_bytes()
            require(digest(raw)==item['sha256'],'Input changed during request preparation')
            mime='image/png' if raw.startswith(b'\x89PNG') else 'image/jpeg' if raw.startswith(b'\xff\xd8') else 'image/webp'
            body+=f'--{boundary}\r\nContent-Disposition: form-data; name="image[]"; filename="reference-{i}"\r\nContent-Type: {mime}\r\n\r\n'.encode()+raw+b'\r\n'
        body+=f'--{boundary}--\r\n'.encode()
        request=urllib.request.Request(ENDPOINT,data=body,headers={'Authorization':'Bearer '+secret,'Content-Type':'multipart/form-data; boundary='+boundary},method='POST')
        folder=state/f'attempt-{len(attempts)+1:03d}';folder.mkdir()
        save(folder/'request.json',{'endpoint':ENDPOINT,'fields':fields,'inputs':job['inputs'],'plan_sha256':fingerprint,'retries':0})
        save(folder/'attempt.json',{'job':job_id,'utc':now(),'reserved_before_post':True})
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*a,**kw):return None
        result={'status':'unknown','estimated_usd':None,'invoice_verified':False,'retries':0}
        try:
            with urllib.request.build_opener(NoRedirect()).open(request,timeout=300) as response:
                response_bytes=response.read();rid=response.headers.get('x-request-id')
            # Preserve exact successful response even if decoding or output validation fails.
            (folder/'response.json').write_bytes(response_bytes)
            data=json.loads(response_bytes)
            usage=data.get('usage')
            result.update(request_id=rid,usage=usage,estimated_usd=estimate(usage,plan.get('pricing')))
            require(len(data.get('data',[]))==1,'Unexpected output count')
            raw=base64.b64decode(data['data'][0]['b64_json'],validate=True)
            (folder/'raw.bin').write_bytes(raw)
            from PIL import Image
            with Image.open(io.BytesIO(raw)) as image:
                require(image.format==job['fields']['output_format'].upper(),'Unexpected image format')
                durations=[];transparent=[]
                for i in range(getattr(image,'n_frames',1)):
                    image.seek(i);image.load();durations.append(image.info.get('duration'))
                    transparent.append(image.convert('RGBA').getchannel('A').getextrema()[0]==0)
                result['validation']={'size':list(image.size),'frames':len(durations),'durations_ms':durations,'loop':image.info.get('loop'),'transparent_each_frame':all(transparent),'bytes':len(raw)}
            (folder/('raw.'+job['fields']['output_format'])).write_bytes(raw)
            result['status']='success'
        except urllib.error.HTTPError as error:
            result.update(status='http_error',http_status=error.code,billing='unknown')
        except Exception:
            # Do not echo exception text: it may contain credentials or server-supplied secrets.
            result.update(status='request_or_output_error',billing='unknown')
        save(folder/'result.json',result)
        return {'job':job_id,'attempt':folder.name,**result}
    finally:
        lock.unlink()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('plan',type=Path)
    group=p.add_mutually_exclusive_group()
    group.add_argument('--approve',metavar='ACTUAL_USER_AUTHORIZATION')
    group.add_argument('--execute',metavar='JOB_ID')
    group.add_argument('--report',action='store_true')
    a=p.parse_args()
    path=a.plan.resolve()
    try:
        c=json.loads(path.read_text(encoding='utf-8'))
        require(re.fullmatch(r'[A-Za-z0-9_-]+',c.get('batch_id','')),'Invalid batch id')
        mode='approve' if a.approve else 'execute' if a.execute else 'report' if a.report else 'dry-run'
        report=run(path,path.parent/('runs-'+c['batch_id']),mode,a.execute,a.approve)
        print(json.dumps(report,ensure_ascii=False,indent=2))
        if mode=='execute' and report['status']!='success':raise SystemExit(1)
    except (ValueError,OSError,KeyError,TypeError):
        raise SystemExit('Stopped: invalid configuration, missing file/approval, consumed quota or locked batch. No automatic retry. Inspect plan and local ledger without exposing credentials.')

if __name__=='__main__':main()
