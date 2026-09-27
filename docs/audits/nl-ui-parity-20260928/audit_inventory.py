"""Read-only source census. Generated outputs are audit artifacts, not app changes."""
import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from html.parser import HTMLParser

OUT = Path(__file__).parent
ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else OUT
tracked = {line.strip() for line in (OUT/'tracked_sources.txt').read_text(encoding='utf-8').splitlines() if re.match(r'^[\w/.-]+\.(py|js|html|css|cjs)$', line.strip())}
class Controls(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        events = {k:v for k,v in a.items() if k.startswith('on')}
        if events or tag in {'button','input','select','textarea','canvas','form','summary'} or a.get('contenteditable') == 'true':
            self.rows.append({'line':self.getpos()[0],'tag':tag,'id':a.get('id'), 'type':a.get('type'), 'title':a.get('title'), 'i18n':a.get('data-i18n'), 'events':events,'data_ui':{k:v for k,v in a.items() if k.startswith('data-ui')}})

files=[]; symbols=[]; endpoints=[]; handlers=[]; tests=[]
for p in sorted(ROOT.rglob('*')):
    rel=p.relative_to(ROOT).as_posix()
    if not p.is_file() or rel not in tracked:
        continue
    raw=p.read_bytes(); text=raw.decode('utf-8-sig', errors='replace')
    files.append({'path':rel,'lines':len(text.splitlines()),'sha256':hashlib.sha256(raw).hexdigest()})
    if p.suffix=='.py':
        try: tree=ast.parse(text)
        except SyntaxError: continue
        for n in ast.walk(tree):
            if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                symbols.append({'path':rel,'line':n.lineno,'name':n.name,'kind':type(n).__name__})
                if n.name.startswith('test_'): tests.append({'path':rel,'line':n.lineno,'name':n.name})
            if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='route' and n.args and isinstance(n.args[0],ast.Constant):
                endpoints.append({'path':rel,'line':n.lineno,'route':n.args[0].value,'methods':next((ast.literal_eval(k.value) for k in n.keywords if k.arg=='methods'),['GET'])})
    if p.suffix in {'.js','.html'}:
        for i,line in enumerate(text.splitlines(),1):
            if re.search(r'addEventListener\s*\(|\bon(?:click|change|input|pointerdown|mousedown|keydown|contextmenu)\s*=',line):
                handlers.append({'path':rel,'line':i,'source':line.strip()[:800]})

parser=Controls(); parser.feed((ROOT/'web/app/index.html').read_text(encoding='utf-8-sig'))
module=ast.parse((ROOT/'tool_factory/ui_controller/__init__.py').read_text(encoding='utf-8-sig'))
registry=next(ast.literal_eval(n.value) for n in module.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CONTROL_REGISTRY' for t in n.targets))
out={'baseline':'a3aa976844526195756a36beebc2828b165e9c33','missing_files':sorted(tracked-{f['path'] for f in files}),'files':files,'symbols':symbols,'routes':endpoints,'static_html_controls':parser.rows,'event_registration_sites':handlers,'ui_control_registry':registry,'test_functions':tests}
(OUT/'audit_inventory.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'files':len(files),'missing':out['missing_files'],'source_lines':sum(f['lines'] for f in files),'production_routes':sum(e['path'].startswith('web/') for e in endpoints),'html_controls':len(parser.rows),'event_sites':len(handlers),'ui_targets':len(registry),'ui_target_command_pairs':sum(len(x['commands']) for x in registry.values()),'test_functions':len(tests)},ensure_ascii=False))
