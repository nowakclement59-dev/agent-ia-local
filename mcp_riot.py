import sys, json
from skills.lol_stats import execute as lol_exec
TOOLS = [{'name': 'lol_stats', 'description': 'Stats LoL Riot/OP.GG', 'inputSchema': {'type': 'object', 'properties': {'region': {'type': 'string'}, 'summoner_name': {'type': 'string'}}, 'required': ['summoner_name']}}]
for line in sys.stdin:
    if not line.strip(): continue
    req = json.loads(line.strip())
    m, rid, params = req.get('method'), req.get('id'), req.get('params') or {}
    if m == 'initialize': sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': rid, 'result': {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}}, 'clientInfo': {'name': 'local-mcp', 'version': '1.0'}}}) + '\n')
    elif m == 'tools/list': sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': rid, 'result': {'tools': TOOLS}}) + '\n')
    elif m == 'tools/call':
        out, err = lol_exec(params.get('arguments') or {})
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': rid, 'result': {'content': [{'type': 'text', 'text': out}], 'isError': err}}) + '\n')
    sys.stdout.flush()