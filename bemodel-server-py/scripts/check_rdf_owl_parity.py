"""Golden Turtle exports, SHACL violation sets, and OWL import previews."""
import json
import re
from pathlib import Path
import httpx
from check_flow_parity import differences

clients = [httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=120) for port in (18080, 18081)]
checks = []
try:
    for client in clients:
        client.headers['Authorization'] = 'Bearer '+client.post('/api/auth/login', json=dict(username='admin', password='admin123')).json()['data']['token']
    patients = clients[0].get('/api/flow/patients?pageSize=200').json()['data']['list']
    for patient in patients:
        code = patient['inhos_no']
        responses = [client.get('/api/rdf/patient/'+code) for client in clients]
        normalized = [re.sub(r'(?m)(.*导出时间：)[^\n]*', r'\1<TIMESTAMP>', response.text) for response in responses]
        diff = list(differences(*normalized))
        checks.append(dict(scenario='Turtle '+code, differences=diff))
        for header in ('content-type', 'content-disposition'):
            if responses[0].headers.get(header) != responses[1].headers.get(header):
                diff.append(dict(path=header, java=responses[0].headers.get(header), python=responses[1].headers.get(header)))
        results = [client.post('/api/rdf/validate/'+code).json() for client in clients]
        engines = [result['data'].pop('engine') for result in results]
        assert engines == ['Apache Jena SHACL 5.2.0', 'pySHACL']
        for result in results:
            result['data']['violations'].sort(key=lambda row: json.dumps(row, sort_keys=True))
        checks.append(dict(scenario='SHACL '+code, implementationEngines=engines, differences=list(differences(*results))))
    fixtures = [('sample.ttl', b'''@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.org/parity/> .
ex:ParityParent a owl:Class . ex:ParityChild a owl:Class; rdfs:subClassOf ex:ParityParent .
ex:age a owl:DatatypeProperty; rdfs:domain ex:ParityChild .
ex:partOf a owl:ObjectProperty, owl:TransitiveProperty; rdfs:domain ex:ParityChild; rdfs:range ex:ParityParent .'''),
        ('sample.owl', b'''<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:owl="http://www.w3.org/2002/07/owl#" xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"><owl:Class rdf:about="http://example.org/parity/ParityXml"><rdfs:label>XML class</rdfs:label></owl:Class></rdf:RDF>''')]
    for name, content in fixtures:
        results = [client.post('/api/ontology/import/preview', files={'file': (name, content)}).json() for client in clients]
        checks.append(dict(scenario='OWL preview '+name, differences=list(differences(*results))))
finally:
    for client in clients:
        client.close()
destination = Path(__file__).resolve().parents[1] / 'artifacts/rdf-owl-parity.json'
destination.write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
failed = [c for c in checks if c['differences']]
print(f'{len(checks)} RDF/SHACL/OWL scenarios, {len(failed)} mismatches (engine identity explicitly checked separately)')
for row in failed[:5]:
    print(row['scenario'], json.dumps(row['differences'], ensure_ascii=True)[:1800])
raise SystemExit(bool(failed))
