from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
import argparse
import copy
import datetime
import html
import json
import mimetypes
import os
import re
import threading
import uuid
import atexit
import math

from agent import Codex

HERE = Path(__file__).resolve().parent
ROOT = next(parent for parent in HERE.parents if (parent / "AGENTS.md").is_file())

UNIT_REGISTRY = {
    'asthma': HERE / 'unit.json',
    'pte': HERE / 'pte_unit.json'
}

UNITS = {}
for uid, ufile in UNIT_REGISTRY.items():
    if ufile.exists():
        try:
            UNITS[uid] = json.loads(ufile.read_text(encoding='utf-8'))
        except Exception as e:
            print(f'Error reading {ufile}: {e}')

# Default fallback: first registered unit, not a hardcoded disease id.
DEFAULT_UNIT_ID = next(iter(UNIT_REGISTRY), 'asthma')
UNIT = UNITS.get(DEFAULT_UNIT_ID, {})
SECTIONS = {s['id']: s for s in UNIT.get('sections', [])}
QUESTIONS = {q['id']: q for q in UNIT.get('questions', [])}
for q in UNIT.get('questions', []):
    if q.get('qid'):
        QUESTIONS[q['qid']] = q

def now():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')

class Store:
    def __init__(self, path, unit_data=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.unit = unit_data or UNIT
        initial_section = self.unit['sections'][0]['id'] if self.unit.get('sections') else 'nature'
        self.data = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {
            'version': 1,
            'unit': self.unit.get('id', 'default-unit'),
            'unitVersion': self.unit.get('version', '1.0'),
            'section': initial_section,
            'threadId': None,
            'messages': [],
            'notes': [],
            'attempts': [],
            'updatedAt': now()
        }
        for key in ('annotations', 'knowledgeNotes', 'recallAnswers'):
            self.data.setdefault(key, [])

    def save(self):
        self.data['updatedAt'] = now()
        tmp = self.path.with_suffix('.json.tmp')
        with tmp.open('w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
        self.export()

    def export(self):
        title = self.unit.get('title', '医学试用记录')
        stem = self.path.stem
        suffix = stem.split('_', 1)[1] if '_' in stem else ''
        export_name = f'试用记录_{suffix.upper()}.md' if suffix else '试用记录.md'
        lines = [
            f'# {title}｜本机试用记录', '',
            f'> 派生可读视图；唯一试用原始记录为同目录 {self.path.name}。不是正式笔记或掌握结论。', '',
            f'更新：{self.data["updatedAt"]}',
            f'当前阅读位置：{self.data["section"]}',
            f'Codex会话：{self.data.get("threadId") or "尚未开始"}', '',
            '## 问答记录', ''
        ]
        for m in self.data['messages']:
            lines.extend([f'### {m["role"]} · {m["time"]} · {m.get("section","")}', m['text'], ''])
        lines.extend(['## 真实试用作答', ''])
        for a in self.data['attempts']:
            lines.extend([f'- {a["question"]}：选择{a["choice"]}；思路：{a["reason"]}；{a["time"]}'])
        lines.extend(['', '## 待核补充（未自动归入正式笔记）', ''])
        for n in self.data['notes']:
            lines.extend([f'- {n["text"]}（来源：{", ".join(n["sources"])}；关联段落：{n["section"]}）'])
        lines.extend(['', '## 讲义勾画与题后积累', ''])
        for n in self.data['annotations'] + self.data['knowledgeNotes']:
            if not n.get('deleted'):
                src = n.get('sourceId', 'tt-handout')
                pg = n.get('page', 1)
                nid = n.get('id', '')
                lines.append(f'- {n.get("note") or n.get("text") or n.get("quote", "框选")}（{src} PDF{pg}；{nid}）')
        lines.extend(['', '## 随堂提取（未自动评定掌握）', ''])
        for a in self.data['recallAnswers']:
            lines.append(f'- {a["recall"]}：{a["text"]}；{a["time"]}')
        tmp = self.path.with_name(export_name + '.tmp')
        tmp.write_text('\n'.join(lines), encoding='utf-8')
        os.replace(tmp, self.path.with_name(export_name))

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.data)

HANDOUT_PAGES_CACHE = {}
AGENT_TURN_LOCK = threading.Lock()

def get_handout_pages_for_unit(unit_data):
    uid = unit_data.get('id', 'default')
    if uid in HANDOUT_PAGES_CACHE:
        return HANDOUT_PAGES_CACHE[uid]
    pages_map = {}
    try:
        import pymupdf
        source = unit_data.get('sources', {}).get('tt-handout', {})
        p = ROOT / source.get('path', '')
        if p.exists():
            with pymupdf.open(p) as doc:
                for idx, pg in enumerate(doc):
                    pages_map[idx + 1] = pg.get_text()
    except Exception:
        pass
    HANDOUT_PAGES_CACHE[uid] = pages_map
    return pages_map

def extract_keywords(query):
    stop = {'有没有', '讲过', '什么是', '这个', '那个', '老师', '我们', '请问', '怎么', '为什么', '如何', '大家', '这里', '好像', '知道', '可以', '一下', '主讲'}
    clean = query
    for s in stop:
        clean = clean.replace(s, ' ')
    terms = set()
    for en in re.findall(r'[a-zA-Z0-9]+', query):
        if len(en) >= 2:
            terms.add(en)
    segments = re.findall(r'[\u4e00-\u9fa5]+', clean)
    for seg in segments:
        if len(seg) in (2, 3):
            terms.add(seg)
        elif len(seg) > 3:
            for i in range(len(seg) - 1):
                terms.add(seg[i:i+2])
            for i in range(len(seg) - 2):
                terms.add(seg[i:i+3])
    return [t for t in terms if len(t) >= 2 and t not in stop]

def search_unit_context(query, section, unit_data, origin=None):
    pages = get_handout_pages_for_unit(unit_data)
    sections = {s['id']: s for s in unit_data.get('sections', [])}
    current_sec = sections.get(section, {})
    
    current_ctx = {'section': current_sec.get('title', ''), 'keypoints': current_sec.get('keypoints', {})}
    orig_pages = current_sec.get('original', {}).get('pages') or [current_sec.get('original', {}).get('page', 1)]
    current_text = '\n'.join([pages.get(p, '') for p in orig_pages if p in pages])
    current_ctx['original_text'] = current_text[:8000]

    selected_origin = None
    if isinstance(origin, dict):
        sid = origin.get('sourceId')
        pg = origin.get('page')
        src = unit_data.get('sources', {}).get(sid, {})
        if (sid == 'tt-handout'
                and src.get('fingerprint') == origin.get('sourceVersion')
                and type(pg) is int
                and 1 <= pg <= src.get('pages', 0)):
            selected_origin = {
                'sourceId': sid,
                'page': pg,
                'text': pages.get(pg, '')[:6000]
            }

    keywords = extract_keywords(query)
    related_pages = []
    if keywords:
        for p_no, p_txt in pages.items():
            if p_no in orig_pages:
                continue
            hits = [w for w in keywords if w in p_txt]
            if hits:
                matching_paras = []
                for para in p_txt.split('\n'):
                    para_clean = para.strip()
                    if any(w in para_clean for w in hits) and len(para_clean) > 5:
                        matching_paras.append(para_clean)
                excerpt = ' '.join(matching_paras[:4])
                sec_match = next((s for s in unit_data.get('sections', []) if p_no in (s.get('original', {}).get('pages') or [s.get('original', {}).get('page')])), None)
                sec_title = sec_match['title'] if sec_match else f'第 {p_no} 页'
                related_pages.append({
                    'page': p_no,
                    'section': sec_title,
                    'hits': hits,
                    'excerpt': excerpt[:600]
                })
        related_pages.sort(key=lambda x: len(x['hits']), reverse=True)

    related_questions = []
    if keywords:
        for q in unit_data.get('questions', []):
            q_txt = q['stem'] + ' ' + q.get('explanation', '')
            hits = [w for w in keywords if w in q_txt]
            if hits:
                related_questions.append({
                    'id': q['id'],
                    'exam': q['exam'],
                    'stem': q['stem'][:100],
                    'hits': hits,
                    'explanation': q.get('explanation', '')[:300]
                })
        related_questions.sort(key=lambda x: len(x['hits']), reverse=True)

    overview_links = []
    for link in unit_data.get('overview', {}).get('links', []):
        l_txt = link.get('title', '') + ' ' + link.get('text', '') + ' '.join(link.get('chain', []))
        if any(w in l_txt for w in keywords):
            overview_links.append(link)

    result = {
        'current_section': current_ctx,
        'selected_origin': selected_origin,
        'cross_page_findings': related_pages[:3],
        'cross_question_findings': related_questions[:2],
        'mind_map_connections': overview_links[:2]
    }
    return json.dumps(result, ensure_ascii=False)

PROMPT_HEADER = '''你是考研西医综合与执业医师资深主讲教师与临床答疑助手。
你拥有该单元整套主讲课程原讲义的完整全文索引、思维导图、全部真题题库与口诀秒杀要诀。
回答核心原则：
1. 全讲义全局视野：
   当用户询问某个概念“主讲老师有没有讲过”、“全篇在哪里出现过”、“分类依据是什么”：
   - 综合利用提供的全讲义线索，明确指出讲义具体页码出处；
   - 严禁因为当前小节未详述就武断宣称“老师没讲过”或“材料未提供”！
   - 先给出清晰的分类结论或对比表，再用主讲老师的推导逻辑和大白话解释机制，最后指出考点。
2. 跨学科与跨科目联动：
   考研西医综合是一门整体学科。当用户探讨疾病机制与生理学（通气/换气/凝血）、诊断学（体征/分型/心电图）、病理学（血栓栓塞/肺出血性梗死）的关系时，调动专业医学知识，为学生解释背后的生理与病理机制，帮助学生串联成网。
3. 语言风格：
   专业扎实、逻辑推导清晰、条理分明。重点突出，善于总结口诀与题眼，就近标明讲义页码或课程来源。
若本次产生了真正值得保留的新澄清，可在最终回答末尾附一行<!-- STUDY_NOTE {"text":"简短的待核补充","sources":["已登记来源id"]} -->；仅为待核，不声称已修改正式笔记。没有增量则不附。不得输出原始密钥或账户信息。
'''

def source_context(section,origin=None):
    s=SECTIONS.get(section, {})
    import pymupdf
    a=s.get('original')
    result={'section':s.get('title',''),'keypoints':s.get('keypoints',{})}
    if isinstance(origin,dict):
        source=UNIT['sources'].get(origin.get('sourceId'),{})
        pg=origin.get('page')
        if source.get('fingerprint')==origin.get('sourceVersion') and type(pg) is int and 1<=pg<=source.get('pages',0):
            a={'sourceId':origin['sourceId'],'page':pg}
    if a:
        source=UNIT['sources'].get(a['sourceId'], {})
        page_no = a.get('page') or (a.get('pages', [1])[0] if isinstance(a.get('pages'), list) else 1)
        try:
            with pymupdf.open(ROOT/source['path']) as pdf:
                text=pdf[page_no-1].get_text()
            result['original']={'sourceId':a['sourceId'],'label':source.get('label',''),'page':page_no,'version':source.get('fingerprint',''),'text':text[:12000]}
        except Exception:
            pass
    return json.dumps(result,ensure_ascii=False)

def base_instructions():
    return PROMPT_HEADER

class Application:
    def __init__(self, data_dir, agent=None, live_enabled=None, session_filename='session.json', unit_data=None):
        self.unit = unit_data or UNIT
        self.sections = {s['id']: s for s in self.unit.get('sections', [])}
        self.questions = {q['id']: q for q in self.unit.get('questions', [])}
        for q in self.unit.get('questions', []):
            if q.get('qid'):
                self.questions[q['qid']] = q

        self.store = Store(Path(data_dir) / session_filename, unit_data=self.unit)
        self.agent = agent or Codex(ROOT)
        if live_enabled is None:
            config = HERE / 'live-config.json'
            live_enabled = json.loads(config.read_text(encoding='utf-8')).get('enabled', False) if config.exists() else False
        self.live_enabled = bool(live_enabled)
        self.run_lock = threading.Lock()
        self.busy = False
        self.partial = ''
        self.status = '可以提问'
        self.error = None
        self.turn_id = None
        self.thread_id = None

    def historical_question_id(self, question_id):
        if self.unit is UNITS.get('pte') and question_id == 'tt-pte-1':
            return 'tt-pte-01'
        return question_id

    def state(self):
        snapshot = self.store.snapshot()
        reviews = {}
        for attempt in snapshot['attempts']:
            question_id = self.historical_question_id(attempt.get('question'))
            if question_id != attempt.get('question'):
                attempt['question'] = question_id
            q = self.questions.get(question_id)
            if q and 'feedback' in q and attempt.get('answer'):
                reviews[q['id']] = dict(
                    explanation=q['explanation'],
                    feedback=q['feedback'],
                    version=q['feedback'].get('version', self.unit.get('version', '1.0'))
                )
        return {
            **snapshot,
            'reviews': reviews,
            'busy': self.busy,
            'partial': self.partial,
            'status': self.status,
            'error': self.error,
            'liveAvailable': self.live_enabled or not isinstance(self.agent, Codex)
        }

    def event(self, kind, value):
        if kind == 'thread':
            self.thread_id = value
            with self.store.lock:
                self.store.data['threadId'] = value
                self.store.save()
        elif kind == 'turn':
            self.turn_id = value
        elif kind == 'partial':
            self.partial = re.sub(r'<!--\s*STUDY_NOTE[\s\S]*', '', value)
        elif kind == 'status':
            self.status = value

    def ask(self, payload):
        if isinstance(self.agent, Codex) and not self.live_enabled:
            raise ValueError('真实问答尚未启用。启用前需确认通过 Codex 向 OpenAI 发送本单元教学内容和问题。')
        section = payload.get('section', self.unit['sections'][0]['id'] if self.unit.get('sections') else 'nature')
        if section not in self.sections:
            raise ValueError('未知段落')
        text = str(payload.get('text', '')).strip()
        if not text or len(text) > 12000:
            raise ValueError('问题不能为空或超过12000字。')
        rid = payload.get('requestId')
        if not isinstance(rid, str) or not 1 <= len(rid) <= 100:
            raise ValueError('请求编号无效。')
        with self.store.lock:
            if any(m.get('requestId') == rid for m in self.store.data['messages']):
                return {'duplicate': True}
        if not self.run_lock.acquire(blocking=False):
            raise BlockingIOError('上一条回答仍在进行，可停止后再问。')
        try:
            with self.store.lock:
                self.store.data['messages'].append({
                    'id': uuid.uuid4().hex,
                    'role': 'user',
                    'text': text,
                    'section': section,
                    'selection': str(payload.get('selection', ''))[:2000],
                    'question': payload.get('question') if payload.get('question') in self.questions else None,
                    'origin': payload.get('origin') if isinstance(payload.get('origin'), dict) else None,
                    'time': now(),
                    'requestId': rid
                })
                self.store.save()
            self.busy = True
            self.error = None
            self.partial = ''
            self.status = '正在回答…'
            worker = threading.Thread(target=self._answer, args=(payload, section, text), daemon=True)
            worker.start()
        except Exception:
            self.busy = False
            self.run_lock.release()
            raise
        return {'saved': True}

    def _answer(self, payload, section, text):
        try:
            context = search_unit_context(text, section, self.unit, payload.get('origin'))
            qid = payload.get('question')
            question = self.questions.get(qid)
            prompt = f'用户当前学习小节及全单元讲义/导图/真题检索召回线索：\n{context}\n'
            if question:
                with self.store.lock:
                    answered = any(
                        self.historical_question_id(a['question']) == qid
                        for a in self.store.data['attempts']
                    )
                visible = {k: v for k, v in question.items() if k not in ('feedback', 'answer', 'explanation')}
                if answered:
                    visible.update(answer=question['answer'], explanation=question['explanation'], feedback=question.get('feedback'))
                prompt += f'当前关联真题信息：\n{json.dumps(visible, ensure_ascii=False)}\n'
            selection = payload.get('selection')
            if selection:
                prompt += f'用户在原貌讲义中勾选文字：\n{selection}\n'
            prompt += f'用户疑问：{text}'

            thread_id = self.store.data.get('threadId')
            with AGENT_TURN_LOCK:
                thread_id, full = self.agent.answer(prompt, thread_id, PROMPT_HEADER, self.event)
            study_note = None
            match = re.search(r'<!--\s*STUDY_NOTE\s+({[\s\S]*?})\s*-->', full)
            if match:
                try:
                    payload_note = json.loads(match.group(1))
                    text_note = str(payload_note.get('text', '')).strip()
                    sources = [str(s) for s in payload_note.get('sources', []) if s in self.unit.get('sources', {})]
                    if text_note and sources:
                        study_note = {
                            'id': uuid.uuid4().hex,
                            'text': text_note,
                            'sources': sources,
                            'section': section,
                            'status': '待核',
                            'createdAt': now()
                        }
                except Exception:
                    pass
            clean_text = re.sub(r'<!--\s*STUDY_NOTE[\s\S]*', '', full).strip()
            with self.store.lock:
                self.store.data['messages'].append({
                    'id': uuid.uuid4().hex,
                    'role': 'assistant',
                    'text': clean_text,
                    'section': section,
                    'time': now(),
                    'requestId': payload.get('requestId')
                })
                if study_note:
                    self.store.data['notes'].append(study_note)
                self.store.save()
            self.status = '可以提问'
        except Exception as e:
            self.error = str(e)
            self.status = '回答中断'
            with self.store.lock:
                self.store.data['messages'].append({
                    'id': uuid.uuid4().hex,
                    'role': 'error',
                    'text': f'回答未能完成：{e}',
                    'section': section,
                    'time': now()
                })
                self.store.save()
        finally:
            self.busy = False
            self.partial = ''
            self.run_lock.release()

    def attempt(self, p):
        q = self.questions.get(p.get('question'))
        if not q:
            raise ValueError('未知题目')
        raw_choice = str(p.get('choice', '')).strip().upper()
        choice = ''.join(sorted(set(raw_choice)))
        option_keys = {o['key'] for o in q['options']}
        if not choice or any(k not in option_keys for k in choice):
            raise ValueError('无效选项')
        reason = str(p.get('reason', '')).strip()
        if len(reason) > 12000:
            raise ValueError('思路过长')
        result = dict(
            answer=q['answer'],
            explanation=q['explanation'],
            correct=set(choice) == set(q['answer']),
            choice=choice,
            reason=reason
        )
        if 'feedback' in q:
            result['feedback'] = q['feedback']
        source = self.unit.get('sources', {}).get('tt-handout', {})
        source_version = source.get('fingerprint')
        with self.store.lock:
            self.store.data['attempts'].append(dict(result, question=q['id'], time=now()))
            note = q.get('feedback', {}).get('note')
            if note:
                notes = self.store.data['knowledgeNotes']
                note_id = note.get('id') if isinstance(note, dict) else q['id']
                note_text = note.get('text') if isinstance(note, dict) else str(note)
                target_page = q.get('feedback', {}).get('targetPage', q.get('targetPage', 1))
                first_sec_id = self.unit['sections'][0]['id'] if self.unit.get('sections') else 'nature'
                target_topic = q.get('feedback', {}).get('targetSection', q.get('section', first_sec_id))
                item = next((n for n in notes if n.get('id') == note_id), None)
                if item is None:
                    item = {
                        'id': note_id,
                        'text': note_text,
                        'evidence': [],
                        'everWrong': False,
                        'deleted': False,
                        'createdAt': now(),
                        'topic': target_topic,
                        'sourceId': 'tt-handout',
                        'sourceVersion': source_version,
                        'page': target_page
                    }
                    if isinstance(note, dict):
                        item.update(note)
                    notes.append(item)
                else:
                    item['text'] = note_text
                    item['page'] = target_page
                    item['topic'] = target_topic
                    item['sourceVersion'] = source_version
                if q['id'] not in item['evidence']:
                    item['evidence'].append(q['id'])
                item['everWrong'] = item['everWrong'] or not result['correct']
                item['updatedAt'] = now()
            self.store.save()
        return result

    def annotate(self, p):
        source = self.unit.get('sources', {}).get(p.get('sourceId'), {})
        if not source.get('fingerprint') or p.get('sourceVersion') != source['fingerprint']:
            raise ValueError('讲义版本不匹配，请重新打开原页再勾画。')
        if type(p.get('page')) is not int or not 1 <= p['page'] <= source.get('pages', 100):
            raise ValueError('页码无效')
        rects = p.get('rects')
        if not isinstance(rects, list) or not 1 <= len(rects) <= 200:
            raise ValueError('请选择原页上的文字或区域')
        for r in rects:
            if not isinstance(r, list) or len(r) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in r):
                raise ValueError('位置格式无效')
            x, y, w, h = r
            if min(x, y) < 0 or min(w, h) <= 0 or x + w > 1.00001 or y + h > 1.00001:
                raise ValueError('位置超出原页')
        if p.get('topic') not in self.sections:
            raise ValueError('未知段落')
        item = {k: copy.deepcopy(p[k]) for k in ('sourceId', 'sourceVersion', 'page', 'rects', 'topic')}
        item.update(
            id=uuid.uuid4().hex,
            quote=str(p.get('quote', ''))[:4000],
            note=str(p.get('note', ''))[:4000],
            createdAt=now(),
            deleted=False
        )
        with self.store.lock:
            self.store.data['annotations'].append(item)
            self.store.save()
        return item

    def annotation_status(self, p):
        with self.store.lock:
            item = next((n for n in self.store.data['annotations'] + self.store.data['knowledgeNotes'] if n['id'] == p.get('id')), None)
            if item is None:
                raise ValueError('未找到这条记录')
            item['deleted'] = p['deleted']
            self.store.save()
            return copy.deepcopy(item)

    def recall(self, p):
        r = next((r for r in self.unit.get('recalls', []) if r['id'] == p.get('recall')), None)
        if not r:
            raise ValueError('未知提取问题')
        value = str(p.get('text', '')).strip()
        if not value or len(value) > 6000:
            raise ValueError('请先写下回忆，或写“暂时想不起来”')
        item = dict(recall=r['id'], text=value, time=now(), reference=r['answer'])
        with self.store.lock:
            self.store.data['recallAnswers'].append(item)
            self.store.save()
        return item


def make_handler(apps, port):
    if isinstance(apps, Application):
        apps = {DEFAULT_UNIT_ID: apps}
    default_app = apps.get(DEFAULT_UNIT_ID, list(apps.values())[0])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def safe_host(self):
            return self.headers.get('Host') in [f'127.0.0.1:{port}', f'localhost:{port}']

        def origin_ok(self):
            origin = self.headers.get('Origin')
            return origin in (f'http://127.0.0.1:{port}', f'http://localhost:{port}')

        def send(self, status, data, kind='application/json; charset=utf-8'):
            b = json.dumps(data, ensure_ascii=False).encode() if kind.startswith('application/json') else data if isinstance(data, bytes) else data.encode()
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(b)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; worker-src 'self' blob:; font-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'")
            self.end_headers()
            try:
                self.wfile.write(b)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def resolve_app_and_unit(self, parsed_query):
            params = parse_qs(parsed_query)
            unit_id = params.get('unit', [DEFAULT_UNIT_ID])[0]
            app = apps.get(unit_id, default_app)
            unit_data = UNITS.get(unit_id, UNIT)
            return app, unit_data, unit_id

        def do_GET(self):
            if not self.safe_host():
                return self.send(403, {'error': '仅接受本机入口。'})
            parsed = urlparse(self.path)
            path = parsed.path

            params = parse_qs(parsed.query)
            requested_unit = params.get('unit', [None])[0]
            if requested_unit and requested_unit not in apps and path != '/api/units':
                return self.send(404, {'error': f'未注册的单元：{requested_unit}'})
            app, unit_data, unit_id = self.resolve_app_and_unit(parsed.query)

            if path == '/api/units':
                units_summary = []
                for uid, u in UNITS.items():
                    lecture = u.get('metadata', {}).get('lecture', '')
                    book = u.get('metadata', {}).get('pages', '')
                    tag = u.get('tag', '')
                    units_summary.append({
                        'id': uid,
                        'title': u.get('title', uid),
                        'lecture': lecture,
                        'book': book,
                        'tag': tag,
                        'status': u.get('status', '')
                    })
                return self.send(200, units_summary)

            if path == '/api/state':
                return self.send(200, app.state())

            if path == '/api/unit':
                data = copy.deepcopy(unit_data)
                for source in data.get('sources', {}).values():
                    source.pop('path', None)
                for recall in data.get('recalls', []):
                    recall.pop('answer', None)
                return self.send(200, data)

            if path.startswith('/vendor/'):
                p = (HERE / path[1:]).resolve()
                if not p.is_relative_to(HERE / 'vendor') or not p.is_file():
                    return self.send(404, {'error': '不存在的资源'})
                kind = 'text/javascript' if p.suffix == '.mjs' else mimetypes.guess_type(p.name)[0] or 'application/octet-stream'
                return self.send(200, p.read_bytes(), kind)

            if path in ('/', '/index.html', '/app.js', '/style.css', '/original-reader.js', '/original.css'):
                p = HERE / ('index.html' if path in ('/', '/index.html') else path[1:])
                return self.send(200, p.read_bytes(), mimetypes.guess_type(p.name)[0] + '; charset=utf-8')

            if path.startswith('/source/'):
                key = path[len('/source/'):]
                source = unit_data.get('sources', {}).get(key)
                if not source:
                    return self.send(404, {'error': f'未登记的来源：{key}'})

                if source.get('kind') == 'web':
                    self.send_response(302)
                    self.send_header('Location', source['url'])
                    self.end_headers()
                    return

                if source.get('kind') == 'pdf':
                    p = (ROOT / source['path']).resolve()
                    if not p.is_relative_to(ROOT):
                        return self.send(403, {'error': '非法来源路径'})
                    if not p.is_file():
                        return self.send(404, {'error': f'找不到本地PDF文件：{p.name}'})
                    return self.send(200, p.read_bytes(), 'application/pdf')

                p = HERE.parent / 'evidence' / f'{key}.txt'
                if not p.is_file():
                    return self.send(404, {'error': '该来源尚无可读文本。'})
                content = p.read_text(encoding='utf-8')
                term = parse_qs(parsed.query).get('find', [''])[0][:100]
                escaped = html.escape(content)
                if term:
                    escaped = escaped.replace(html.escape(term), '<mark>' + html.escape(term) + '</mark>')
                page = f'<!doctype html><meta charset="utf-8"><title>{html.escape(source["label"])}</title><style>body{{max-width:900px;margin:40px auto;padding:0 20px;font:18px/1.9 sans-serif}}pre{{white-space:pre-wrap}}mark{{background:#ffe49b}}</style><h1>{html.escape(source["label"])}</h1><p>原课程转录，可能有识别错误；不是经校准正文。可用Ctrl+F查找。</p><pre>{escaped}</pre>'
                return self.send(200, page, 'text/html; charset=utf-8')

            return self.send(404, {'error': '不存在的入口'})

        def do_POST(self):
            if not self.safe_host() or not self.origin_ok():
                return self.send(403, {'error': '拒绝外部网页发起写入。'})
            if not self.headers.get('Content-Type', '').startswith('application/json'):
                return self.send(415, {'error': '需要JSON'})

            parsed = urlparse(self.path)
            path = parsed.path

            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 70000:
                    return self.send(413, {'error': '请求大小不适合'})
                p = json.loads(self.rfile.read(length))
                if not isinstance(p, dict):
                    raise ValueError('请求格式错误')

                # Unit from payload or query
                unit_id = p.get('unit') or parse_qs(parsed.query).get('unit', [DEFAULT_UNIT_ID])[0]
                if unit_id not in apps:
                    return self.send(404, {'error': f'未注册的单元：{unit_id}'})
                app = apps[unit_id]

                if path == '/api/ask':
                    return self.send(202, app.ask(p))
                if path == '/api/attempt':
                    return self.send(200, app.attempt(p))
                if path == '/api/annotation':
                    return self.send(200, app.annotate(p))
                if path == '/api/annotation-status':
                    return self.send(200, app.annotation_status(p))
                if path == '/api/recall':
                    return self.send(200, app.recall(p))
                if path == '/api/position':
                    if p.get('section') not in app.sections:
                        raise ValueError('未知位置')
                    with app.store.lock:
                        app.store.data['section'] = p['section']
                        app.store.save()
                    return self.send(200, {'saved': True})
                if path == '/api/stop':
                    if app.turn_id and app.thread_id:
                        app.agent.call('turn/interrupt', {'threadId': app.thread_id, 'turnId': app.turn_id}, 10)
                    return self.send(200, {'requested': True})

                return self.send(404, {'error': '不存在的操作'})
            except BlockingIOError as e:
                return self.send(409, {'error': str(e)})
            except (ValueError, KeyError, TypeError) as e:
                return self.send(400, {'error': str(e)})
            except Exception as e:
                return self.send(500, {'error': '操作未成功：' + str(e)[:300]})

    return Handler

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--port', type=int, default=8766)
    p.add_argument('--data-dir', default=str(HERE / 'data'))
    args = p.parse_args()

    shared_agent = Codex(ROOT)
    atexit.register(shared_agent.close)

    apps = {}
    for uid, udata in UNITS.items():
        sfile = 'session.json' if uid == DEFAULT_UNIT_ID else f'session_{uid}.json'
        apps[uid] = Application(args.data_dir, agent=shared_agent, session_filename=sfile, unit_data=udata)

    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(apps, args.port))
    print(f'本机试用（已挂载多单元）：http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        shared_agent.close()

if __name__ == '__main__':
    main()
