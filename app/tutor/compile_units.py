#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
compile_units.py: 标准化、全量医学教辅单元编译器
负责将主讲老师讲义、思维导图、全量题库执医真题（带高频热评）与考研西综拔高题深度清洗并编译为 unit.json 与 pte_unit.json。
"""

import json
import re
import pathlib
import docx

TUTOR = pathlib.Path(__file__).resolve().parent
ROOT = next(parent for parent in TUTOR.parents if (parent / 'AGENTS.md').is_file())

def load_unit_source(filename, fallback):
    """Load hand-authored unit content, not the generated output."""
    source = TUTOR / 'content' / filename
    if not source.is_file():
        source = TUTOR / fallback
    if not source.is_file():
        raise FileNotFoundError(f'缺少单元内容源文件：{TUTOR / "content" / filename}（也不存在回退 {fallback}）')
    return json.loads(source.read_text(encoding='utf-8'))

def parse_ykb_jsonl(path, default_section, default_page, prefix, tier, exam_tag, topic_classifier=None):
    questions = []
    lines = open(path, encoding='utf-8').readlines()
    for idx, line in enumerate(lines):
        if not line.strip():
            continue
        item = json.loads(line)
        # Stem
        raw_stem = item.get('stem', '')
        if isinstance(raw_stem, list):
            raw_stem = ''.join(raw_stem)
        raw_stem = raw_stem.strip()
        m_qid = re.match(r'^([0-9]{4}[A-Za-z0-9-]+)\s+(.*)', raw_stem)
        if m_qid:
            qid_str, stem_text = m_qid.group(1), m_qid.group(2)
        else:
            qid_str = f'{prefix}-{idx+1:02d}'
            stem_text = raw_stem

        # Options
        raw_options = item.get('options', [])
        options = []
        for opt in raw_options:
            opt = opt.strip()
            m_opt = re.match(r'^([A-E])\.\s*(.*)', opt)
            if m_opt:
                options.append({'key': m_opt.group(1), 'text': m_opt.group(2)})
            elif opt:
                options.append({'key': chr(65 + len(options)), 'text': opt})
        if not options:
            continue

        # Answer
        raw_ans = item.get('answer', '')
        if isinstance(raw_ans, list):
            raw_ans = ''.join(raw_ans)
        m_ans = re.search(r'正确答案\s*([A-E])', raw_ans) or re.search(r'答案[：:]\s*([A-E])', raw_ans)
        ans = m_ans.group(1) if m_ans else 'A'

        # Explanation
        secs = item.get('official_sections', {})
        exp_parts = []
        for k, v in secs.items():
            if k == 'tv_edit_time':
                continue
            if isinstance(v, list):
                exp_parts.append('\n'.join(v))
            elif isinstance(v, str):
                exp_parts.append(v)
        explanation = '\n\n'.join(exp_parts).strip() or '题库解析与教材依据'

        # Comments：按 votes 降序提纯，保留前两条为结构化“高频热评”
        cmts = item.get('comments', []) or []

        def _comment_text(c):
            if c.get('text_blocks'):
                return ' '.join(c['text_blocks']).strip()
            if c.get('text'):
                return str(c['text']).strip()
            return ''

        def _comment_votes(c):
            raw = c.get('votes', 0)
            if isinstance(raw, (int, float)):
                return int(raw)
            m = re.search(r'(\d+)', str(raw).replace(',', ''))
            return int(m.group(1)) if m else 0

        def _comment_author(c):
            raw = c.get('author', '热心考友')
            if isinstance(raw, list):
                return str(raw[0]) if raw else '热心考友'
            return str(raw or '热心考友')

        ranked_comments = sorted(
            [c for c in cmts if _comment_text(c)],
            key=_comment_votes,
            reverse=True,
        )
        comment_notes = []
        comment_insights = []
        for c in ranked_comments:
            c_text = _comment_text(c)
            author = _comment_author(c)
            votes = _comment_votes(c)
            comment_notes.append(f'【{author}】：{c_text}')
            if len(comment_insights) < 2:
                comment_insights.append({
                    'title': f'👍 {votes} 赞 · {author}',
                    'text': c_text[:1200]
                })

        # Topic and Page classification
        sec = default_section
        pg = default_page
        if topic_classifier:
            sec, pg = topic_classifier(stem_text, explanation)

        note_text = f'【真题题眼】记在主讲讲义 P{pg}：' + stem_text[:35] + f' ➔ 选 {ans}'
        if comment_notes:
            note_text += f'（热评秒杀：{comment_notes[0][:40]}）'

        questions.append({
            'id': f'{prefix}-{idx+1:02d}',
            'qid': qid_str,
            'tier': tier,
            'tierLabel': '🥈 执考题',
            'exam': f'{exam_tag} · {qid_str}',
            'stem': stem_text,
            'options': options,
            'answer': ans,
            'multi': len(ans) > 1,
            'explanation': explanation,
            'feedback': {
                'derivation': explanation[:300],
                'note': note_text,
                'commentInsights': comment_insights,
                'targetSection': sec,
                'targetPage': pg
            }
        })
    return questions

def parse_kaoyan_docx(path, prefix, topic_classifier):
    doc = docx.Document(path)
    paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    ans_map = {}
    ans_start = False
    exp_start = False
    exp_map = {}
    current_exp_num = None

    q_blocks = []
    current_q = None

    for p in paras:
        if '【参考答案汇总】' in p:
            ans_start = True
            exp_start = False
            continue
        if '【题目解析汇总】' in p:
            ans_start = False
            exp_start = True
            continue

        if ans_start:
            m = re.match(r'(\d+)~(\d+):([A-E\-]+)', p)
            if m:
                s, e, seq = int(m.group(1)), int(m.group(2)), m.group(3).split('-')
                for i, a in enumerate(seq):
                    ans_map[s + i] = a
            continue

        if exp_start:
            m_exp = re.match(r'^(\d+)\.\s*(.*)', p)
            if m_exp:
                current_exp_num = int(m_exp.group(1))
                exp_map[current_exp_num] = m_exp.group(2)
            elif current_exp_num:
                exp_map[current_exp_num] += '\n' + p
            continue

        m_q = re.match(r'^(\d+)、(\d{4}[A-Za-z0-9]+)\s*(.*)', p)
        if m_q:
            if current_q:
                q_blocks.append(current_q)
            current_q = {
                'num': int(m_q.group(1)),
                'qid': m_q.group(2),
                'stem': m_q.group(3),
                'options': []
            }
        elif current_q:
            m_opt = re.match(r'^([A-E])\.\s*(.*)', p)
            if m_opt:
                current_q['options'].append({'key': m_opt.group(1), 'text': m_opt.group(2)})
            else:
                current_q['stem'] += ' ' + p

    if current_q:
        q_blocks.append(current_q)

    questions = []
    for q in q_blocks:
        num = q['num']
        ans = ans_map.get(num, 'A')
        exp = exp_map.get(num, '西综考研真题详细解析与机制依据')
        sec, pg = topic_classifier(q['stem'], exp)
        questions.append({
            'id': f'{prefix}-{num:02d}',
            'qid': q['qid'],
            'tier': 'tier3',
            'tierLabel': '🥉 考研题',
            'exam': f'西综考研 · {q["qid"]}',
            'stem': q['stem'],
            'options': q['options'],
            'answer': ans,
            'multi': len(ans) > 1,
            'explanation': exp,
            'feedback': {
                'derivation': exp[:300],
                'note': f'【考研必背】记在主讲讲义 P{pg}：' + q['stem'][:35] + f' ➔ 选 {ans}',
                'targetSection': sec,
                'targetPage': pg
            }
        })
    return questions

# ----------------- PTE 编译器 -----------------
def classify_pte(stem, exp):
    text = stem + ' ' + exp
    if any(k in text for k in ['溶栓', '休克', '低血压', '危险分层', '大面积', '次大面积', '死亡率']):
        return 'pte-severity', 5
    if any(k in text for k in ['抗凝', '肝素', '华法林', '利伐沙班', '疗程', '至少3个月', '动次撒', '出血']):
        return 'pte-treatment', 4
    if any(k in text for k in ['CTPA', '造影', '心电图', 'SⅠQⅢTⅢ', 'D-二聚体', '血气', '核素', 'V/Q', '确诊', '首选检查']):
        return 'pte-diagnosis', 3
    if any(k in text for k in ['呼吸困难', '胸痛', '咯血', '三联征', 'P2亢进', '发绀', '下肢肿胀', 'Homans']):
        return 'pte-symptoms', 2
    return 'pte-nature', 1

def compile_pte():
    print("Compiling PTE (主讲 004)...")
    pte_base = load_unit_source('pte_content.json', 'pte_unit.json')

    # 主讲课后题 8 题
    # ------------------------------------------------------------------
    # 【公开展示版说明】
    # 原实现此处硬编码了作者整理的 8 道真实考研真题（题干、选项、答案、解析），
    # 涉及第三方题库版权，公开版不提供原文。下面用 1 道原创占位示例保留数据结构，
    # 仅用于说明字段形状，不是真实题目，也不构成任何医学建议。
    # 本地完整版的数据结构与这里一致；公开包因此不能按原样运行。
    # ------------------------------------------------------------------
    tt_questions = [
        {
            'id': 'tt-pte-01',
            'qid': 'EXAMPLE-01',
            'tier': 'tier1',
            'tierLabel': '示例占位',
            'exam': '示例占位 · 非真实题目',
            'section': 'pte-diagnosis',
            'stem': '（示例占位）此处原为一道真实考研真题的题干，公开版已移除。',
            'options': [
                {'key': 'A', 'text': '示例选项 A'},
                {'key': 'B', 'text': '示例选项 B'},
                {'key': 'C', 'text': '示例选项 C'},
                {'key': 'D', 'text': '示例选项 D'},
            ],
            'answer': 'A',
            'explanation': '公开版不提供真实题目解析。',
            'feedback': {
                'derivation': '公开版占位说明。',
                'note': '公开版占位说明。',
                'targetSection': 'pte-diagnosis',
                'targetPage': 3,
            },
        }
    ]

    # 题库执医 59 题
    ykb_path = ROOT / '04_资料库/课程原始资料/02_医学课程/01_大四课程/01_内科学/04_习题/执业医师题库/肺血栓栓塞症/questions-and-comments.jsonl'
    ykb_questions = parse_ykb_jsonl(ykb_path, 'pte-diagnosis', 3, 'ykb-pte', 'tier2', '执考真题', classify_pte)

    # 考研 DOCX 17 题
    docx_path = ROOT / '04_资料库/课程原始资料/02_医学课程/01_大四课程/01_内科学/04_习题/考研真题库/第二篇 第十一章 肺血栓栓塞症.docx'
    ky_questions = parse_kaoyan_docx(docx_path, 'ky-pte', classify_pte)

    for idx, q in enumerate(tt_questions, 1):
        q['qid'] = f'TT-PTE-{idx:02d}'
        q['exam'] = f'主讲课后 · 第{idx}题'
        q['stem'] = re.sub(r'^（[0-9]{4}[A-Za-z0-9-]+）\s*', '', q['stem']).strip()
        q['tier'] = 'tier1'
        q['tierLabel'] = '🥇 主讲课后题'

    all_pte_questions = tt_questions + ykb_questions + ky_questions
    print(f"PTE Total questions assembled: {len(all_pte_questions)} (tt: {len(tt_questions)}, ykb: {len(ykb_questions)}, ky: {len(ky_questions)})")
    pte_base['questions'] = all_pte_questions
    pte_base['status'] = f"课程原讲义全量7页 (书页24~30) + 跨学科病理生理贯通 + {len(all_pte_questions)}题三梯队"
    
    # 确保小节配置通用化
    for s in pte_base['sections']:
        if 'practice' in s['id']:
            s['type'] = 'practice'

    pte_base['metadata'] = {
        'lecture': '主讲课程 · 第1.3讲',
        'pages': '原讲义共 7 页 · 24 ~ 30 页'
    }
    json.dump(pte_base, open(TUTOR / 'pte_unit.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f"PTE unit successfully updated to {TUTOR / 'pte_unit.json'}!")

# ----------------- 哮喘 编译器 -----------------
def classify_asthma(stem, exp):
    text = stem + ' ' + exp
    if any(k in text for k in ['危重', '轻度', '中度', '重度', '分度', '奇脉', '胸腹矛盾', '沉默肺', '气胸', '机械通气']):
        return 'severity', 6
    if any(k in text for k in ['SABA', 'ICS', '激素', '沙丁胺醇', '茶碱', '白三烯', '孟鲁司特', '受体', '控制评估']):
        return 'treatment', 4
    if any(k in text for k in ['激发', '舒张', 'PEF', '变异率', '肺功能', 'FEV1', '可逆', '诊断标准']):
        return 'tests', 3
    if any(k in text for k in ['表现', '咳嗽变异', '哮鸣音', '端坐呼吸', '干咳', '夜间']):
        return 'symptoms', 2
    if any(k in text for k in ['COPD', '慢阻肺', '心源性', '心衰', '左心', '鉴别']):
        return 'diagnosis', 9
    return 'nature', 1

def compile_asthma():
    print("Compiling Asthma (主讲 008)...")
    asthma_base = load_unit_source('asthma_content.json', 'unit.json')

    # 保留原主讲课后题 8 题；全部改为本地稳定编号，避免与考研 DOCX 的 qid 重复。
    # 固定记录 8 道题在 DOCX 中对应的原始 qid，保证多次编译结果一致。
    tt_questions = [q for q in asthma_base['questions'] if q['id'].startswith('tt-')]
    tt_source_qids = {
        '2016N65A', '2020N44A', '2020N68A', '2020N69A',
        '2021N43A', '2023N42A', '2024N43A', '2002N59A',
    }
    for idx, q in enumerate(tt_questions, 1):
        q['qid'] = f'TT-ASTHMA-{idx:02d}'
        q['exam'] = f'主讲课后 · 第{idx}题'
        q['stem'] = re.sub(r'^（[0-9]{4}[A-Za-z0-9-]+）\s*', '', q['stem']).strip()
        q['tier'] = 'tier1'
        q['tierLabel'] = '🥇 主讲课后题'

    # 读取题库全量 121 题
    asthma_ykb_path = ROOT / '04_资料库/课程原始资料/02_医学课程/01_大四课程/01_内科学/04_习题/执业医师题库/支气管哮喘完整版/questions-and-comments.jsonl'
    ykb_questions = parse_ykb_jsonl(asthma_ykb_path, 'treatment', 4, 'ykb-asthma', 'tier2', '执考真题', classify_asthma)

    # 考研 DOCX 全量：46 题；与 tier1 同 qid 的 8 题已归入主讲课后，不重复计入 tier3。
    ky_docx_path = ROOT / '04_资料库/课程原始资料/02_医学课程/01_大四课程/01_内科学/04_习题/考研真题库/第二篇 第四章 支气管哮喘.docx'
    parsed_ky = parse_kaoyan_docx(ky_docx_path, 'ky2-asthma', classify_asthma)
    ky_questions = [q for q in parsed_ky if q['qid'] not in tt_source_qids]
    for q in ky_questions:
        q['tier'] = 'tier3'
        q['tierLabel'] = '🥉 考研题'

    all_asthma_questions = tt_questions + ykb_questions + ky_questions
    print(f"Asthma Total questions assembled: {len(all_asthma_questions)} (tt: {len(tt_questions)}, ykb: {len(ykb_questions)}, ky: {len(ky_questions)})")
    asthma_base['questions'] = all_asthma_questions
    asthma_base['status'] = f"课程原讲义全量10页 + 伴随干货面板 + {len(all_asthma_questions)}题三梯队"

    for s in asthma_base['sections']:
        if 'practice' in s['id']:
            s['type'] = 'practice'

    asthma_base['metadata'] = {
        'lecture': '主讲课程 · 第1.9讲',
        'pages': '原讲义共 10 页 · 64 ~ 73 页'
    }
    json.dump(asthma_base, open(TUTOR / 'unit.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f"Asthma unit successfully updated to {TUTOR / 'unit.json'}!")

if __name__ == '__main__':
    compile_pte()
    compile_asthma()
    print("All units successfully compiled and ready!")
