from pathlib import Path
import json,time
from server import Application

app=Application(Path(__file__).parent/'qa-data')
try:
    app.ask({'section':'tests','text':'这是接入测试，不计本人学习：FEV1和一秒率是一个东西吗？请用两三句话区分，并给本单元来源。','requestId':'qa-live-1'})
    end=time.time()+360
    while app.busy and time.time()<end: time.sleep(.5)
    s=app.state()
    print(json.dumps({'busy':s['busy'],'error':s['error'],'messages':s['messages'][-2:]},ensure_ascii=False),flush=True)
    if app.error: raise RuntimeError(app.error)
    if app.busy: raise RuntimeError('test timed out')
finally: app.agent.close()
