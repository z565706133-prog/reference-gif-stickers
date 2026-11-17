"""Dry-run by default; optionally GET official model list. Never generates images."""
import argparse
import json
import os
import urllib.request
import urllib.error

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-models',action='store_true')
    parser.add_argument('--model',action='append',default=[])
    args=parser.parse_args()
    key=os.environ.get('OPENAI_API_KEY','').strip()
    report={'key_present':bool(key),'mode':'model-list' if args.check_models else 'dry-run',
        'image_requests_sent':0,'images_permissions':'unverified'}
    if not args.check_models:
        print(json.dumps(report));return
    if not key:
        report['result']='missing_key';print(json.dumps(report));raise SystemExit(1)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*a,**kw):return None
    request=urllib.request.Request('https://api.openai.com/v1/models',headers={'Authorization':'Bearer '+key})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request,timeout=30) as response:
            data=json.load(response);report['http_status']=response.status
        available={m['id'] for m in data.get('data',[]) if isinstance(m,dict) and 'id' in m}
        report['models']={m:m in available for m in args.model}
        report['result']='model_list_accessible'
    except urllib.error.HTTPError as error:
        report.update(http_status=error.code,result='http_error')
    except Exception:
        report['result']='connection_or_response_error'
    print(json.dumps(report))
    if report['result']!='model_list_accessible':raise SystemExit(1)

if __name__=='__main__':main()
