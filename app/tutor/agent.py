"""Local Codex stdio adapter. No credentials are copied or exposed."""
import json
import queue
import shutil
import subprocess
import threading
import time

class Codex:
    def __init__(self, cwd):
        self.cwd = str(cwd)
        self.proc = None
        self.pending = {}
        self.events = queue.Queue()
        self.lock = threading.Lock()
        self.serial = 0
        self.stderr_lines = []

    def _drain_stderr(self):
        try:
            for line in self.proc.stderr:
                text = (line or '').strip()
                if text:
                    self.stderr_lines.append(text)
                    if len(self.stderr_lines) > 30:
                        self.stderr_lines.pop(0)
        except Exception:
            pass

    def start(self):
        if self.proc and self.proc.poll() is None:
            return
        executable = shutil.which('codex')
        if not executable:
            raise RuntimeError('未找到已安装的Codex。')
        self.proc = subprocess.Popen([executable, 'app-server', '--stdio'], cwd=self.cwd,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace', bufsize=1,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._drain_stderr, daemon=True).start()
        try:
            self.call('initialize', {'clientInfo': {'name':'medical-study-trial','version':'0.1.0'}})
        except Exception as e:
            detail = ' | '.join(self.stderr_lines[-3:])
            self.close()
            raise RuntimeError(f'Codex启动失败：{e}' + (f'；{detail}' if detail else '')) from e
        self.send({'method':'initialized', 'params':{}})

    def _read(self):
        try:
            for line in self.proc.stdout:
                try: obj=json.loads(line)
                except ValueError: continue
                if 'id' in obj and 'method' in obj:
                    # Never silently approve tool access or external side effects.
                    self.send({'id':obj['id'],'error':{'code':-32601,'message':'当前试用仅允许只读、无审批的操作。'}})
                elif 'id' in obj:
                    q=self.pending.get(obj['id'])
                    if q: q.put(obj)
                else:
                    self.events.put(obj)
        finally:
            for q in list(self.pending.values()):
                q.put({'error':{'message':'Codex连接已关闭。'}})
            self.events.put({'method':'transport/closed','params':{}})

    def send(self,obj):
        with self.lock:
            self.proc.stdin.write(json.dumps(obj,ensure_ascii=False)+'\n')
            self.proc.stdin.flush()

    def call(self,method,params,timeout=60):
        self.serial+=1; i=self.serial; q=queue.Queue(); self.pending[i]=q
        try:
            self.send({'id':i,'method':method,'params':params})
            try: msg=q.get(timeout=timeout)
            except queue.Empty: raise RuntimeError('Codex响应超时：'+method)
            if 'error' in msg: raise RuntimeError(msg['error'].get('message','Codex调用失败'))
            return msg.get('result',{})
        finally:
            self.pending.pop(i,None)

    def close(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try: self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired: self.proc.kill()

    def answer(self,prompt,thread_id,base,on_event):
        self.start()
        if thread_id:
            self.call('thread/resume',{'threadId':thread_id})
        else:
            r=self.call('thread/start',{'cwd':self.cwd,'sandbox':'read-only','approvalPolicy':'never',
                'developerInstructions':base,'config':{'project_doc_max_bytes':0,'web_search':'disabled','features.shell_tool':False}})
            thread_id=r['thread']['id']
        on_event('thread',thread_id)
        while not self.events.empty():
            self.events.get_nowait()
        result=self.call('turn/start',{'threadId':thread_id,'input':[{'type':'text','text':prompt}],
            'approvalPolicy':'never','sandboxPolicy':{'type':'readOnly'},'effort':'medium'})
        turn_id=result['turn']['id']; on_event('turn',turn_id)
        messages={}; phases={}; deadline=time.time()+360
        while time.time()<deadline:
            try: event=self.events.get(timeout=1)
            except queue.Empty: continue
            method=event.get('method'); p=event.get('params',{})
            if method=='transport/closed': raise RuntimeError('Codex连接中断，已保留你的问题。')
            if p.get('threadId') not in (None,thread_id): continue
            if method=='item/started':
                item=p.get('item',{})
                if item.get('type')=='agentMessage': phases[item['id']]=item.get('phase')
                elif item.get('type') in ('commandExecution','mcpToolCall'): on_event('status','正在核对资料…')
            elif method=='item/agentMessage/delta':
                k=p.get('itemId','reply'); messages[k]=messages.get(k,'')+p.get('delta','')
                on_event('partial', '\n\n'.join(messages.values()))
            elif method=='item/completed':
                item=p.get('item',{})
                if item.get('type')=='agentMessage':
                    messages[item['id']]=item.get('text',''); phases[item['id']]=item.get('phase')
            elif method=='turn/completed':
                turn=p.get('turn',{})
                if turn.get('status')!='completed':
                    error=turn.get('error') or {}
                    raise RuntimeError(error.get('message') or ('已停止生成。' if turn.get('status')=='interrupted' else '本次回答未完成。'))
                final=[v for k,v in messages.items() if phases.get(k)=='final_answer']
                answer='\n\n'.join(final or list(messages.values())).strip()
                if not answer: raise RuntimeError('模型未返回可显示的回答。')
                return thread_id,answer
        try: self.call('turn/interrupt',{'threadId':thread_id,'turnId':turn_id},10)
        except Exception: pass
        raise RuntimeError('回答超过等待时限，已保留问题，可以重试。')
