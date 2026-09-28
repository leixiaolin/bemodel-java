"""Read-only CORS comparison against original Java and current Python ASGI code."""
import json
from pathlib import Path
import httpx
from fastapi.testclient import TestClient
from bemodel.main import create_app
from check_flow_parity import differences


def normalized(response):
    try:
        body = response.json()
    except ValueError:
        body = response.text
    return dict(status=response.status_code,body=body,headers={
        k:sorted(v.split(', ')) if k == 'vary' else v
        for k,v in response.headers.items() if k.startswith('access-control-') or k == 'vary'})


def main():
    checks=[]
    with httpx.Client(base_url='http://127.0.0.1:18083') as java, TestClient(create_app(startup=False)) as python:
        scenarios=[('OPTIONS','/api/concept/list',{'Origin':'https://example.invalid','Access-Control-Request-Method':method,
            'Access-Control-Request-Headers':'authorization,content-type'}) for method in ('GET','POST','PUT','DELETE','PATCH','PROPFIND')]
        scenarios += [
            ('OPTIONS','/outside',{'Origin':'https://example.invalid','Access-Control-Request-Method':'GET'}),
            ('OPTIONS','/api',{'Origin':'null','Access-Control-Request-Method':'POST'}),
            ('OPTIONS','/api/concept/list',{}),
            ('GET','/api/concept/list',{'Origin':'https://example.invalid'}),
            ('GET','/api/concept/list',{}),
            ('OPTIONS','/api/concept/list',{'Origin':'<same-origin>','Access-Control-Request-Method':'GET'}),
        ]
        for method,path,headers in scenarios:
            responses=[]
            for client in (java,python):
                origin=str(client.base_url).rstrip('/')
                adapted={k:origin if v=='<same-origin>' else v for k,v in headers.items()}
                responses.append(normalized(client.request(method,path,headers=adapted)))
            checks.append(dict(method=method,path=path,headers=headers,responses=responses,differences=list(differences(*responses))))
    destination=Path(__file__).resolve().parents[1]/'artifacts/cors-parity.json'
    destination.write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
    failed=[c for c in checks if c['differences']]
    print(f'{len(checks)} CORS/authentication cases, {len(failed)} differences')
    for item in failed:
        print(json.dumps(item,ensure_ascii=True))
    raise SystemExit(bool(failed))


if __name__ == '__main__':
    main()
