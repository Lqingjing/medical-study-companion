"""Explicitly authorized real calls; isolated from user learning records."""
import json,time,uuid
from pathlib import Path
from server import Application,UNIT

directory=Path(__file__).parent/'qa-live-authorized'
app=Application(directory,live_enabled=True)
def turn(app,text,**extra):
    app.ask(dict(section='tests',text=text,requestId=uuid.uuid4().hex,**extra))
    deadline=time.time()+420
    while app.busy and time.time()<deadline:time.sleep(.25)
    if app.busy:raise RuntimeError('test wait timeout')
    if app.error:raise RuntimeError(app.error)
    last=app.state()['messages'][-1]
    assert last['role']=='assistant' and last['text'].strip()
    print(last['text'],flush=True)
try:
    turn(app,'仅用两三句话解释：舒张试验和激发试验分别证明什么？标明本次讲义页。',selection='支气管舒张试验阳性',origin={'sourceId':'tt-handout','page':3,'sourceVersion':UNIT['sources']['tt-handout']['fingerprint']})
    saved_thread=app.state()['threadId'];assert saved_thread
finally:app.agent.close()
app=Application(directory,live_enabled=True)
try:
    assert app.state()['threadId']==saved_thread
    turn(app,'接着刚才这两个试验说：我把两者目的记反了，给我一句对照记法即可。')
    assert app.state()['threadId']==saved_thread
    print(json.dumps({'passed':True,'messages':len(app.state()['messages']),'restarted':True,'threadPreserved':True},ensure_ascii=False),flush=True)
finally:app.agent.close()
