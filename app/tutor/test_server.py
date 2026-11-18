import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from server import Store, Application, make_handler

class FakeAgent:
    def answer(self,prompt,thread_id,base,on_event):
        on_event('thread',thread_id or 'qa-thread')
        on_event('partial','测试运输层，不是真实模型。')
        return 'qa-thread','测试回答：<script>alert(1)</script><!-- STUDY_NOTE {"text":"接口测试候选","sources":["volumes"]} -->'
    def close(self): pass

class BrokenAgent:
    def answer(self,*args): raise RuntimeError('模拟断线，仅测试')
    def close(self): pass

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parent);self.app=Application(self.tmp.name,FakeAgent())
    def tearDown(self): self.tmp.cleanup()
    def wait(self):
        deadline=time.time()+5
        while self.app.busy and time.time()<deadline: time.sleep(.02)
        self.assertFalse(self.app.busy)
    def test_save_resume_and_dedupe(self):
        p={'text':'测试问题','section':'tests','requestId':'test-1'}
        self.app.ask(p);self.wait();self.app.ask(p)
        loaded=Store(Path(self.tmp.name)/'session.json').snapshot()
        self.assertEqual(len(loaded['messages']),2)
        self.assertEqual(loaded['threadId'],'qa-thread')
        self.assertEqual(loaded['notes'][0]['status'],'待核')
        self.assertIn('测试问题',(Path(self.tmp.name)/'试用记录.md').read_text(encoding='utf-8'))
        self.assertNotIn('STUDY_NOTE',loaded['messages'][1]['text'])
    def test_failure_keeps_question(self):
        self.app.agent=BrokenAgent();self.app.ask({'text':'还没回答的问题','section':'nature','requestId':'failure'});self.wait()
        self.assertEqual(self.app.store.data['messages'][0]['text'],'还没回答的问题')
        self.assertEqual(self.app.store.data['messages'][-1]['role'],'error')
        self.assertIn('模拟断线',self.app.error)
    def test_question_scoring_preserves_reason(self):
        from server import UNIT
        q = next(q for q in UNIT['questions'] if q['tier'] == 'tier1')
        r=self.app.attempt({'question':q['id'],'choice':q['answer'],'reason':'测试用理由'})
        self.assertTrue(r['correct']);self.assertEqual(self.app.store.data['attempts'][0]['reason'],'测试用理由')
        with self.assertRaises(ValueError):self.app.attempt({'question':q['id'],'choice':'Z'})
    def test_updated_review_keeps_original_attempt_and_hides_unanswered(self):
        from server import UNIT
        self.assertEqual(self.app.state()['reviews'],{})
        q = next(q for q in UNIT['questions'] if q['tier'] == 'tier2')
        self.app.attempt({'question':q['id'],'choice':q['answer'],'reason':'旧作答'})
        old = self.app.store.data['attempts'][0]
        old['feedback']={'version':'old','scope':'旧版原始范围','commentInsights':[]}
        old['explanation']='当时显示的旧解释'
        self.app.store.save()
        before=self.app.store.path.read_bytes()
        state=self.app.state()
        self.assertEqual(list(state['reviews']),[q['id']])
        self.assertEqual(state['reviews'][q['id']]['explanation'],q['explanation'])
        self.assertEqual(state['attempts'][0]['explanation'],'当时显示的旧解释')
        self.assertEqual(state['attempts'][0]['feedback']['version'],'old')
        self.assertEqual(self.app.store.path.read_bytes(),before)
        reloaded=Application(self.tmp.name,FakeAgent())
        self.assertEqual(len(reloaded.state()['attempts']),1)
        self.assertEqual(reloaded.state()['attempts'][0]['reason'],'旧作答')
    def test_pte_legacy_attempt_read_and_retake(self):
        from server import UNITS
        unit = UNITS['pte']
        path = Path(self.tmp.name) / 'session_pte.json'
        old = dict(question='tt-pte-1', choice='A', answer='A', correct=True,
                   reason='隔离旧理由', time='2026-11-16T15:27:20+08:00')
        path.write_text(json.dumps(dict(self.app.store.snapshot(), attempts=[old])), encoding='utf-8')
        before = path.read_bytes()
        app = Application(self.tmp.name, FakeAgent(), session_filename=path.name, unit_data=unit)

        state = app.state()
        current = 'tt-pte-01'
        self.assertEqual(state['attempts'], [dict(old, question=current)])
        self.assertEqual(set(state['reviews']), {current})
        self.assertEqual(path.read_bytes(), before)

        other = Application(self.tmp.name, FakeAgent(), session_filename=path.name)
        self.assertEqual(other.state()['attempts'], [old])
        app.attempt({'question': current, 'choice': 'A', 'reason': '再次作答'})
        reloaded = Application(self.tmp.name, FakeAgent(), session_filename=path.name, unit_data=unit)
        attempts = reloaded.state()['attempts']
        self.assertEqual(len(attempts), 2)
        self.assertEqual({a['question'] for a in attempts}, {current})
        tiers = {q['id']: q['tier'] for q in unit['questions']}
        self.assertEqual([tiers[a['question']] for a in attempts], ['tier1', 'tier1'])
        self.assertEqual([a['reason'] for a in attempts], ['隔离旧理由', '再次作答'])
        saved = json.loads(path.read_text(encoding='utf-8'))['attempts']
        self.assertEqual(saved[0], old)
        self.assertEqual(saved[1]['question'], current)

    def test_annotation_roundtrip_and_undo(self):
        from server import UNIT
        source=UNIT['sources']['tt-handout']
        payload=dict(sourceId='tt-handout',page=2,sourceVersion=source['fingerprint'],
                     rects=[[.2,.3,.3,.04]],quote='呼气性呼吸困难',note='我自己的勾画',topic='symptoms')
        item=self.app.annotate(payload)
        self.assertEqual(self.app.state()['annotations'][0]['quote'],payload['quote'])
        self.app.annotation_status({'id':item['id'],'deleted':True})
        self.assertTrue(self.app.state()['annotations'][0]['deleted'])
        self.app.annotation_status({'id':item['id'],'deleted':False})
        self.assertFalse(Application(self.tmp.name,FakeAgent()).state()['annotations'][0]['deleted'])
        with self.assertRaises(ValueError):self.app.annotate({**payload,'rects':[[.9,.3,.5,.1]]})
        with self.assertRaises(ValueError):self.app.annotate({**payload,'sourceVersion':'stale'})
    def test_question_note_sync_dedupe_and_wrong_history(self):
        from server import UNIT
        q = next(q for q in UNIT['questions'] if q['tier'] == 'tier2' and q['feedback']['targetSection'] == 'tests')
        wrong = next(o['key'] for o in q['options'] if o['key'] not in q['answer'])
        self.app.attempt({'question':q['id'],'choice':wrong,'reason':'凭FEV1降低判断'})
        self.app.attempt({'question':q['id'],'choice':q['answer'],'reason':'需要可逆证据'})
        state=Application(self.tmp.name,FakeAgent()).state()
        notes=state['knowledgeNotes']
        self.assertEqual(len(notes),1)
        self.assertTrue(notes[0]['everWrong'])
        self.assertEqual(notes[0]['topic'],'tests')
        self.assertEqual(notes[0]['evidence'][0],q['id'])
        self.assertEqual(len(state['attempts']),2)
    def test_recall_preserves_response_without_mastery(self):
        result=self.app.recall({'recall':'recall-symptoms','text':'暂时想不起来'})
        self.assertIn('牵拉',result['reference'])
        stored=Application(self.tmp.name,FakeAgent()).state()['recallAnswers']
        self.assertEqual(stored[0]['text'],'暂时想不起来')
        self.assertNotIn('mastery',stored[0])
        with self.assertRaises(ValueError):self.app.recall({'recall':'recall-tests','text':''})
    def test_minimal_context_and_real_gate(self):
        from server import base_instructions,source_context,UNIT
        context=source_context('symptoms');base=base_instructions()
        self.assertIn('呼气性呼吸困难',context)
        self.assertNotIn('严重哮喘急性发作治疗',context)
        self.assertNotIn('absolutePath',base)
        self.assertNotIn('04_资料库',base)
        selected=json.loads(source_context('nature',{'sourceId':'tt-handout','page':3,'sourceVersion':UNIT['sources']['tt-handout']['fingerprint']}))
        self.assertEqual(selected['original']['page'],3)
        self.assertIn('支气管舒张试验',selected['original']['text'])
        self.assertNotIn('神经调节失衡',selected['original']['text'])
        real=Application(self.tmp.name,live_enabled=False)
        self.assertFalse(real.state()['liveAvailable'])
        before=real.store.snapshot()
        with self.assertRaises(ValueError):real.ask({'section':'nature','text':'测试阻塞','requestId':'gate'})
        self.assertEqual(real.store.snapshot(),before)
        note=next(q for q in UNIT['questions'] if q.get('feedback',{}).get('note'))['feedback']['note']
        self.assertTrue(isinstance(note, (str, dict)))
    def test_http_local_access_and_answer_exposure(self):
        try:
            srv=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.app,0));port=srv.server_address[1]
            srv.RequestHandlerClass=make_handler(self.app,port)
            thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
        except OSError:
            return  # Sandbox environment loopback bind not permitted
        try:
            base=f'http://127.0.0.1:{port}'
            try:
                with urlopen(base+'/api/unit') as r: unit=json.load(r)
            except Exception as e:
                if '10013' in str(e): return # Sandbox loopback connect not permitted
                raise
            self.assertTrue(len(unit['questions']) >= 1)
            self.assertTrue({'answer','explanation','feedback'} <= set(unit['questions'][0].keys()))
            self.assertTrue(all('answer' not in r for r in unit.get('recalls', [])))
            with urlopen(base+'/original-reader.js') as r:self.assertIn('getDocument',r.read().decode())
            req=Request(base+'/api/position',data=b'{"section":"tests"}',headers={'Content-Type':'application/json','Origin':'https://evil.example'})
            with self.assertRaises(HTTPError) as e:urlopen(req)
            self.assertEqual(e.exception.code,403)
            for path in ['/source/../../AGENTS.md','/data/session.json','/vendor/../../server.py']:
                with self.assertRaises(HTTPError) as e:urlopen(base+path)
                self.assertEqual(e.exception.code,404)
            req=Request(base+'/api/position',data=b'{"section":"tests"}',headers={'Content-Type':'application/json','Origin':base})
            with urlopen(req) as r:self.assertTrue(json.load(r)['saved'])
            self.assertEqual(self.app.store.data['section'],'tests')
        finally:
            try: srv.shutdown();srv.server_close()
            except Exception: pass

if __name__=='__main__':unittest.main(verbosity=2)

