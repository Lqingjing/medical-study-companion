'use strict';
let unit, state, current = 0, context = 'nature', selection = '', currentQuestion = null, lastSignature = '', toastTimer;
let originalHost = null, readerModule = import('./original-reader.js'), selectedOrigin = null, jumpNote = null;
let currentTierFilter = 'all';
let currentUnitId = new URLSearchParams(window.location.search).get('unit') || '';

const $ = id => document.getElementById(id);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

async function api(path, data) {
  const url = new URL(path, window.location.origin);
  if (!url.searchParams.has('unit') && currentUnitId) {
    url.searchParams.set('unit', currentUnitId);
  }
  const r = await fetch(url.toString(), data === undefined ? {} : {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  const x = await r.json();
  if (!r.ok) throw new Error(x.error || '操作未成功');
  return x;
}

function toast(text) {
  $('toast').textContent = text;
  $('toast').hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('toast').hidden = true, 5000);
}

function rich(node, text) {
  String(text).split(/(\*\*[^*]+\*\*)/g).forEach(part => {
    node.append(part.startsWith('**') ? el('strong', '', part.slice(2, -2)) : document.createTextNode(part));
  });
  return node;
}

function paragraphs(text, container) {
  String(text).split(/\n\s*\n/).filter(t => t.trim()).forEach(t => {
    container.append(rich(el('p'), t.trim()));
  });
}

function switchCompanionTab(tabName) {
  const tabPoints = $('tab-points');
  const tabAsk = $('tab-ask');
  const panelPoints = $('companion-points');
  const panelAsk = $('companion-ask');

  if (tabName === 'ask') {
    tabAsk.classList.add('active');
    tabPoints.classList.remove('active');
    panelAsk.hidden = false;
    panelAsk.style.display = 'flex';
    panelPoints.hidden = true;
    panelPoints.style.display = 'none';
  } else {
    tabPoints.classList.add('active');
    tabAsk.classList.remove('active');
    panelPoints.hidden = false;
    panelPoints.style.display = 'flex';
    panelAsk.hidden = true;
    panelAsk.style.display = 'none';
  }
}

function updateCompanionPoints(s) {
  const isPractice = s.type === 'practice' || s.id.includes('practice');
  if (isPractice) {
    renderPracticeCompanion(s);
    return;
  }
  $('panel-section-title').textContent = s.title;

  const ttList = $('tt-points-list');
  ttList.replaceChildren();
  const ttPoints = s.keypoints?.tiantian_mechanism || [];
  if (ttPoints.length) {
    ttPoints.forEach(p => {
      const pNode = el('p');
      rich(pNode, p);
      ttList.append(pNode);
    });
  } else {
    ttList.append(el('p', 'muted-text', '本节对应实战真题练习，可在正文逐题推导检验。'));
  }

  const dmList = $('dm-points-list');
  dmList.replaceChildren();
  const dmPoints = s.keypoints?.damiao_traps || [];
  if (dmPoints.length) {
    dmPoints.forEach(p => {
      const pNode = el('p');
      rich(pNode, p);
      dmList.append(pNode);
    });
  } else {
    dmList.append(el('p', 'muted-text', '执考与月考考点已深度融入下方第二梯队习题热评解析。'));
  }

  const noteText = $('handout-note-text');
  if (s.keypoints?.handout_note) {
    noteText.textContent = s.keypoints.handout_note;
  } else {
    noteText.textContent = '按需将关键题眼与推导步骤批注于讲义对应页空白处。';
  }

  // Cross Discipline Card Update
  renderCrossDisciplineCard(s);
}

function renderCrossDisciplineCard(s) {
  const crossCard = $('cross-card-wrapper');
  const cross = s?.cross_discipline;
  if (cross && crossCard) {
    crossCard.hidden = false;
    const badgeEl = $('cross-badge');
    if (badgeEl) badgeEl.textContent = cross.badge || '西综跨学科';
    const labelEl = $('cross-source-label');
    if (labelEl) labelEl.textContent = cross.sourceLabel || cross.discipline || '';
    const viewBtn = $('view-cross-source-btn');
    if (viewBtn) {
      viewBtn.onclick = () => renderCrossDisciplineView(cross, s);
    }
    const crossList = $('cross-points-list');
    if (crossList) {
      crossList.replaceChildren();
      (cross.points || []).forEach(p => {
        const pNode = el('p');
        rich(pNode, p);
        crossList.append(pNode);
      });
    }
  } else if (crossCard) {
    crossCard.hidden = true;
  }
}

function renderCrossDisciplineView(cross, s) {
  originalHost?.dispose?.();
  originalHost = null;

  const header = el('div', 'cross-view-header');
  const leftInfo = el('div', 'cross-header-left');
  leftInfo.append(
    el('span', 'cross-tag', `🧬 跨学科对照 · ${cross.discipline}`),
    el('strong', 'cross-title', cross.sourceLabel)
  );
  const backBtn = el('button', 'back-to-handout-btn', '👈 返回课程讲义');
  backBtn.onclick = () => {
    renderLesson();
  };
  header.append(leftInfo, backBtn);

  const host = el('div', 'original-reader');
  $('lesson').replaceChildren(header, host);
  mountOriginal(host, cross.sourceId, [cross.page || 1], s.id);
  $('reading').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderPracticeCompanion(s) {
  $('panel-section-title').textContent = '习题实战 · 核心考点速查与复盘';

  const ttList = $('tt-points-list');
  ttList.replaceChildren();
  const highYieldPoints = s.keypoints?.tiantian_mechanism || [];
  if (highYieldPoints.length) {
    highYieldPoints.forEach(p => {
      const pNode = el('p');
      rich(pNode, p);
      ttList.append(pNode);
    });
  } else {
    ttList.append(el('p', 'muted-text', '本单元尚未配置习题核心考点数据。'));
  }

  const dmList = $('dm-points-list');
  dmList.replaceChildren();
  const dmShortcuts = s.keypoints?.damiao_traps || [];
  if (dmShortcuts.length) {
    dmShortcuts.forEach(p => {
      const pNode = el('p');
      rich(pNode, p);
      dmList.append(pNode);
    });
  } else {
    dmList.append(el('p', 'muted-text', '本单元尚未配置习题秒杀口诀数据。'));
  }

  const wrongAttempts = (state?.attempts || []).filter(a => !a.correct);
  if (wrongAttempts.length) {
    const wrongCount = new Set(wrongAttempts.map(a => a.question)).size;
    $('handout-note-text').textContent = `当前共有 ${wrongCount} 道题目曾作答有误，建议点击题卡下方的“围绕这道题问老师”或“跳转回对应讲义页”针对性强化！`;
  } else {
    $('handout-note-text').textContent = s.keypoints?.handout_note || '【做题闭环】先独立判断并留存思路，答完后重点对照热评秒杀法与讲义出处。';
  }

  renderCrossDisciplineCard(s);
}

function setContext(id, question = null, selected = '') {
  context = id;
  currentQuestion = question;
  selection = selected;
  selectedOrigin = null;
  updateContext();
}

function updateContext() {
  const s = unit.sections.find(x => x.id === context) || unit.sections[current];
  $('context-title').textContent = currentQuestion ? `题目 ${currentQuestion} · ${s.title}` : s.title;
  $('selection-note').hidden = !selection;
  $('selection-note').textContent = selection ? '选中重点：' + selection : '';
}

async function navigate(index, scroll = true) {
  current = Math.max(0, Math.min(index, unit.sections.length - 1));
  const s = unit.sections[current];
  history.replaceState(null, '', '#' + s.id);
  renderLesson();
  try {
    await api('/api/position', { section: s.id });
    $('save-state').textContent = '阅读进度已自动保存';
  } catch (e) {
    $('save-state').textContent = '进度保存失败';
    toast(e.message);
  }
  if (scroll) $('reading').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderLesson() {
  originalHost?.dispose?.();
  originalHost = null;

  const s = unit.sections[current];
  $('lesson').replaceChildren();
  $('practice').replaceChildren();
  $('section-minimap').replaceChildren();

  $('section-count').textContent = `${String(current + 1).padStart(2, '0')} / ${unit.sections.length} · ${s.group}`;
  $('lesson').append(el('h2', '', s.title), el('p', 'lesson-subtitle', s.subtitle));

  updateCompanionPoints(s);

  const isPractice = s.type === 'practice' || s.id.includes('practice');
  if (isPractice) {
    renderPracticeSection(s);
  } else if (s.original) {
    renderOriginalSection(s);
  }

  finishNavigation(s);
}

function finishNavigation(s) {
  $('unit-map-nav-btn')?.setAttribute('aria-current', 'false');
  $('previous').disabled = current === 0;
  $('next').disabled = current === unit.sections.length - 1;
  $('toc').querySelectorAll('[data-section]').forEach(b => {
    b.setAttribute('aria-current', String(b.dataset.section === s.id));
  });
  setContext(s.id);
}

function renderOverview(scroll = true) {
  originalHost?.dispose?.();
  originalHost = null;
  history.replaceState(null, '', '#overview');

  $('lesson').replaceChildren();
  $('practice').replaceChildren();
  $('section-minimap').replaceChildren();

  const ov = unit.overview || {};
  const systemLabel = ov.systemLabel || '全局';
  $('section-count').textContent = `导图先行 · ${systemLabel}全局思维导图`;

  $('unit-map-nav-btn')?.setAttribute('aria-current', 'true');
  $('toc').querySelectorAll('[data-section]').forEach(b => b.setAttribute('aria-current', 'false'));

  // Update Companion Panel
  $('panel-section-title').textContent = `思维导图 · ${unit.title}全局坐标`;
  const ttList = $('tt-points-list');
  ttList.replaceChildren();
  const ttBullets = ov.ttBullets || [];
  ttBullets.forEach(b => { const p = el('p'); rich(p, b); ttList.append(p); });
  if (!ttBullets.length) ttList.append(el('p', 'muted-text', '本单元尚未配置导图核心线索。'));

  const dmList = $('dm-points-list');
  dmList.replaceChildren();
  const dmBullets = ov.dmBullets || [];
  dmBullets.forEach(b => { const p = el('p'); rich(p, b); dmList.append(p); });
  if (!dmBullets.length) dmList.append(el('p', 'muted-text', '本单元尚未配置导图秒杀提示。'));

  $('handout-note-text').textContent = ov.handoutNote || '导图用于学前宏观定位与学后闭环复盘。';
  setContext(unit.sections[0]?.id || 'nature');

  // Build Overview Main Area
  const intro = el('div', 'overview-intro-card');
  intro.append(
    el('h3', '', `🗺️ 先把 ${unit.title} 放回${systemLabel}全局版图`),
    el('p', '', ov.intro || `在精读具体讲义前，先沿以下核心脉络定位 ${unit.title}：`),
    el('p', 'muted-text', ov.sourceLabel || '')
  );
  $('lesson').append(intro);

  for (const link of (ov.links || [])) {
    const card = el('section', 'map-relationship');
    card.append(el('h4', '', link.title));

    const chainBox = el('div', 'map-chain');
    (link.chain || []).forEach((c, idx) => {
      if (idx > 0) chainBox.append(el('i', 'map-chain-sep', link.connector || '→'));
      chainBox.append(el('span', 'map-chain-node', c));
    });
    card.append(chainBox);
    card.append(el('p', '', link.text));

    if (link.section) {
      const go = el('button', 'secondary', '📖 前往对应讲义小节');
      go.onclick = () => {
        const idx = unit.sections.findIndex(s => s.id === link.section);
        if (idx >= 0) navigate(idx);
      };
      card.append(go);
    }
    $('lesson').append(card);
  }

  // Mind Map PDF Embed
  const mapPage = ov.mapPage || ov.page || 1;
  const mapBookPage = ov.mapBookPage || ov.printPage || null;
  const mapTopic = ov.mapTopic || unit.title;
  const mapSourceId = ov.sourceId;
  const mapHeadText = mapBookPage
    ? `原版思维导图 · ${systemLabel}（书页 ${mapBookPage} · ${mapTopic}）`
    : `原版思维导图 · ${systemLabel}（${mapTopic}）`;
  const mapHead = el('div', 'page-divider-badge', mapHeadText);
  const host = el('div', 'original-reader');
  $('lesson').append(mapHead, host);
  mountOriginal(host, mapSourceId, [mapPage], unit.sections[0]?.id || 'nature');

  // Bottom Navigation
  const bottomBar = el('div', 'reading-bottom');
  const firstSecTitle = unit.sections[0]?.title || '概念与机制';
  const startBtn = el('button', '', `🚀 进入第 01 节：${firstSecTitle}`);
  startBtn.onclick = () => navigate(0);
  bottomBar.append(el('span', 'muted-text', '随时可点击左侧顶部回到本导图'), startBtn);
  $('lesson').append(bottomBar);

  $('previous').disabled = true;
  $('next').disabled = false;
  if (scroll) $('reading').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function mountOriginal(host, sourceId, pagesOrPage, topic) {
  originalHost = host;
  const jump = jumpNote;
  jumpNote = null;
  try {
    const mod = await readerModule;
    if (!host.isConnected) return;
    const pages = Array.isArray(pagesOrPage) ? pagesOrPage : (pagesOrPage ? [pagesOrPage] : [1]);
    host.reader = await mod.mount(host, {
      sourceId,
      source: unit.sources[sourceId],
      unit: currentUnitId,
      pages,
      page: pages[0],
      topic,
      api,
      notify: toast,
      onAsk: origin => {
        setContext(topic, null, origin.quote || `框选区域：PDF ${origin.page}（按该页文本辅助）`);
        selectedOrigin = origin;
        switchCompanionTab('ask');
        $('question-input').focus();
      }
    });
  } catch (e) {
    host.textContent = '原讲义加载失败：' + e.message;
  }
}

function renderOriginalSection(s) {
  const host = el('div', 'original-reader');
  
  if (s.miniMap && s.miniMap.length) {
    const mapContainer = $('section-minimap');
    s.miniMap.forEach((label, i) => {
      if (i > 0) mapContainer.append(el('span', 'mini-sep', '→'));
      const span = el('span', 'mini-tag', label);
      mapContainer.append(span);
    });
  }

  $('lesson').append(host);
  const pages = s.original.pages || (s.original.page ? [s.original.page] : [1]);
  mountOriginal(host, s.original.sourceId, pages, s.id);
}

function renderPracticeSection(s) {
  const totalCount = unit.questions?.length || 0;
  const t1Count = (unit.questions || []).filter(q => q.tier === 'tier1').length;
  const t2Count = (unit.questions || []).filter(q => q.tier === 'tier2').length;
  const t3Count = (unit.questions || []).filter(q => q.tier === 'tier3').length;

  const practiceIntro = el('div', 'practice-intro-card');
  practiceIntro.append(
    el('h3', '', `课后真题综合实战 · 三大梯队精选（全量 ${totalCount} 题）`),
    el('p', '', '根据学习闭环原则，本节习题按梯队循序推进：'),
    el('ul', 'practice-tier-list', '')
  );
  const list = practiceIntro.querySelector('ul');
  const t1 = el('li');
  t1.innerHTML = `<strong>🥇 第一梯队：课后题（${t1Count}题）</strong> · 紧扣讲义原题，重点检验课上机制推导与速记口诀。`;
  const t2 = el('li');
  t2.innerHTML = `<strong>🥈 第二梯队：执医精选题（${t2Count}题）</strong> · 提纯自高频热评秒杀法，穿插题眼与高频陷阱辨析。`;
  const t3 = el('li');
  t3.innerHTML = `<strong>🥉 第三梯队：考研拓展题（${t3Count}题）</strong> · 针对深度机制计算与疑难病例，拔高实战能力。`;
  list.append(t1, t2, t3);

  // Handout toggle preview
  if (s.original && s.original.pages && s.original.pages.length) {
    const src = unit.sources[s.original.sourceId];
    const bStart = src?.bookStart || 1;
    const pageRange = s.original.pages.map(p => `P${p}`).join('~');
    const bookRange = s.original.pages.map(p => `书页${p + bStart - 1}`).join('~');
    const toggleHandout = el('details', 'practice-handout-toggle');
    toggleHandout.append(el('summary', '', `📖 展开对照课后习题原讲义（${pageRange} · ${bookRange}）`));
    const handoutHost = el('div', 'original-reader practice-reader');
    toggleHandout.append(handoutHost);
    toggleHandout.ontoggle = () => {
      if (toggleHandout.open && !handoutHost.hasChildNodes()) {
        mountOriginal(handoutHost, s.original.sourceId, s.original.pages, s.id);
      }
    };
    $('lesson').append(practiceIntro, toggleHandout);
  } else {
    $('lesson').append(practiceIntro);
  }

  renderPracticeControlsOnly();
}

function renderPracticeControlsOnly() {
  const container = $('practice');
  container.replaceChildren();

  // 1. Question Palette
  container.append(renderQuestionPalette());

  // 2. Tier Filter Nav
  container.append(renderTierFilterBar());

  // 3. Quiz List
  renderQuizzes();
}

function renderQuestionPalette() {
  const card = el('div', 'question-palette-card');
  const header = el('div', 'palette-header');
  header.append(el('strong', '', '📋 本单元做题答题卡 · 点击题号直达'));

  const completedMap = {};
  state.attempts.forEach(a => {
    completedMap[a.question] = a;
  });

  const completedCount = Object.keys(completedMap).length;
  const correctCount = Object.values(completedMap).filter(a => a.correct).length;
  const wrongCount = completedCount - correctCount;

  const stats = el('div', 'palette-stats');
  stats.append(
    el('span', 'stat-item', `已做 ${completedCount}/${unit.questions.length}`),
    el('span', 'stat-item correct', `正确 ${correctCount}`),
    el('span', 'stat-item wrong', `需复盘 ${wrongCount}`)
  );
  header.append(stats);
  card.append(header);

  const grid = el('div', 'palette-grid');
  unit.questions.forEach((q, idx) => {
    const attempt = completedMap[q.id];
    let cls = 'palette-pill';
    if (attempt) {
      cls += attempt.correct ? ' is-correct' : ' is-wrong';
    }
    const pill = el('button', cls, String(idx + 1));
    pill.type = 'button';
    pill.title = `${q.id} · ${q.exam} · ${q.tierLabel || ''}`;
    pill.onclick = () => {
      const qTier = (q.tier === 'tiantian' ? 'tier1' : (q.tier === 'ykb' ? 'tier2' : (q.tier === 'kaoyan' ? 'tier3' : q.tier)));
      if (currentTierFilter !== 'all' && currentTierFilter !== qTier) {
        currentTierFilter = 'all';
        renderPracticeControlsOnly();
      }
      const targetForm = $('quiz-' + q.id);
      if (targetForm) {
        targetForm.scrollIntoView({ behavior: 'smooth', block: 'center' });
        targetForm.classList.add('highlight');
        setTimeout(() => targetForm.classList.remove('highlight'), 1800);
      }
    };
    grid.append(pill);
  });
  card.append(grid);
  return card;
}

function renderTierFilterBar() {
  const nav = el('div', 'tier-nav');
  const counts = {
    all: unit.questions.length,
    tier1: unit.questions.filter(q => q.tier === 'tier1' || q.tier === 'tiantian').length,
    tier2: unit.questions.filter(q => q.tier === 'tier2' || q.tier === 'ykb').length,
    tier3: unit.questions.filter(q => q.tier === 'tier3' || q.tier === 'kaoyan').length
  };

  const completed = {
    all: state.attempts.length,
    tier1: state.attempts.filter(a => { const q = unit.questions.find(x => x.id === a.question); return q && (q.tier === 'tier1' || q.tier === 'tiantian'); }).length,
    tier2: state.attempts.filter(a => { const q = unit.questions.find(x => x.id === a.question); return q && (q.tier === 'tier2' || q.tier === 'ykb'); }).length,
    tier3: state.attempts.filter(a => { const q = unit.questions.find(x => x.id === a.question); return q && (q.tier === 'tier3' || q.tier === 'kaoyan'); }).length
  };

  const tiers = [
    { key: 'all', label: '全部真题' },
    { key: 'tier1', label: '🥇 主讲课后题' },
    { key: 'tier2', label: '🥈 执考精选题' },
    { key: 'tier3', label: '🥉 考研拔高题' }
  ];

  tiers.forEach(t => {
    const btn = el('button', 'tier-btn' + (currentTierFilter === t.key ? ' active' : ''));
    btn.type = 'button';
    btn.append(
      document.createTextNode(t.label),
      el('span', 'tier-count-badge', `${completed[t.key]}/${counts[t.key]}`)
    );
    btn.onclick = () => {
      currentTierFilter = t.key;
      renderPracticeControlsOnly();
    };
    nav.append(btn);
  });

  return nav;
}

function renderQuizzes() {
  const container = $('practice');
  const filtered = unit.questions.filter(q => {
    if (currentTierFilter === 'all') return true;
    if (currentTierFilter === 'tier1') return q.tier === 'tier1' || q.tier === 'tiantian';
    if (currentTierFilter === 'tier2') return q.tier === 'tier2' || q.tier === 'ykb';
    if (currentTierFilter === 'tier3') return q.tier === 'tier3' || q.tier === 'kaoyan';
    return q.tier === currentTierFilter;
  });

  if (!filtered.length) {
    container.append(el('p', 'muted-text', '该梯队暂无题目。'));
    return;
  }

  filtered.forEach((q, idx) => {
    const form = el('form', `quiz tier-${q.tier}`);
    form.id = 'quiz-' + q.id;

    const meta = el('div', 'question-meta');
    const badgeGroup = el('div', 'badge-group');
    badgeGroup.append(
      el('span', `tier-badge tier-${q.tier}`, q.tierLabel || '实战真题'),
      el('span', 'exam-badge', q.exam)
    );
    meta.append(badgeGroup, el('span', 'q-seq', `第 ${idx + 1} 题`));
    form.append(meta);

    form.append(el('p', 'stem', q.stem));

    const previous = [...state.attempts].reverse().find(a => a.question === q.id);
    const multi = q.multi === true || String(q.answer || '').length > 1;

    const optionsBox = el('div', 'options-group');
    q.options.forEach(o => {
      const label = el('label', 'option-label');
      const input = el('input');
      input.type = multi ? 'checkbox' : 'radio';
      input.name = q.id;
      input.value = o.key;
      input.checked = multi
        ? String(previous?.choice || '').includes(o.key)
        : previous?.choice === o.key;
      label.append(input, el('span', 'option-text', `${o.key}. ${o.text}`));
      optionsBox.append(label);
    });
    form.append(optionsBox);

    const reason = el('textarea', 'reason-input');
    reason.placeholder = '可在此记录作答思路、纠结选项或犹豫卡点（留存后可在右侧问老师）';
    reason.setAttribute('aria-label', q.id + '的作答思路');
    reason.value = previous?.reason || '';
    form.append(reason);

    const actions = el('div', 'quiz-actions');
    const submit = el('button', 'btn-submit', previous ? '重新提交验证' : '提交并看解析');
    submit.type = 'submit';

    const peekBtn = el('button', 'secondary btn-peek', '👀 查看解析与回写讲义小记');
    peekBtn.type = 'button';

    const discuss = el('button', 'secondary btn-discuss', '围绕这道题问老师');
    discuss.type = 'button';
    discuss.onclick = () => {
      const targetSection = q.feedback?.targetSection || q.section || context;
      setContext(targetSection, q.id);
      switchCompanionTab('ask');
      const stemBlock = `【题目】${q.id} · ${q.exam}\n【题干】${q.stem}\n`;
      const prefix = `${stemBlock}${reason.value ? `【我的思路】：${reason.value}\n【请教问题】：` : '【请教问题】：'}`;
      $('question-input').value = prefix;
      $('question-input').focus();
    };

    actions.append(submit, peekBtn, discuss);
    form.append(actions);

    const feedback = el('div', 'feedback-container');
    feedback.hidden = !previous;
    form.append(feedback);

    peekBtn.onclick = () => {
      if (feedback.hidden) {
        feedback.hidden = false;
        renderFeedback(feedback, previous || {
          answer: q.answer,
          explanation: q.explanation,
          correct: null,
          feedback: q.feedback,
          choice: [...form.querySelectorAll('input:checked')].map(i => i.value).sort().join('')
        }, q);
        peekBtn.textContent = '🙈 收起解析与小记';
      } else {
        feedback.hidden = true;
        peekBtn.textContent = '👀 查看解析与回写讲义小记';
      }
    };

    if (previous) {
      peekBtn.textContent = '🙈 收起解析与小记';
      renderFeedback(feedback, previous, q);
    }

    form.onsubmit = async e => {
      e.preventDefault();
      const choice = [...form.querySelectorAll('input:checked')].map(i => i.value).sort().join('');
      if (!choice) return toast('请先选择一个选项');
      submit.disabled = true;
      try {
        const r = await api('/api/attempt', { question: q.id, choice, reason: reason.value });
        await poll();
        feedback.hidden = false;
        renderFeedback(feedback, r, q);
        updateCompanionPoints(unit.sections[current]);
        const card = $('practice')?.querySelector('.question-palette-card');
        if (card) {
          card.replaceWith(renderQuestionPalette());
        }
        toast('作答记录与解析已更新');
      } catch (err) {
        toast(err.message);
      } finally {
        submit.disabled = false;
      }
    };

    container.append(form);
  });
}

function renderFeedback(box, x, q) {
  box.replaceChildren();
  box.hidden = false;

  const optionLabel = keys => String(keys || '').split('').filter(Boolean).map(key => {
    const text = q.options.find(o => o.key === key)?.text || '';
    return text ? `${key}. ${text}` : key;
  }).join('；');

  const outcomeClass = x.correct === true ? 'is-correct' : (x.correct === false ? 'is-wrong' : 'is-peek');
  const outcome = el('div', `answer-outcome ${outcomeClass}`);
  if (x.correct !== null && x.correct !== undefined) {
    outcome.append(
      el('h4', '', x.correct ? '🎉 回答正确' : '⚠️ 答案有误，请注意陷阱辨析'),
      el('p', '', `你的选择：${x.choice ? optionLabel(x.choice) : '尚未选择'}`),
      el('p', 'correct-text', `参考答案：${optionLabel(x.answer)}`)
    );
  } else {
    outcome.append(
      el('h4', '', '📖 官方参考答案与核心题眼'),
      el('p', 'correct-text', `标准答案：${optionLabel(x.answer)}`),
      x.choice ? el('p', '', `当前勾选：${optionLabel(x.choice)}`) : el('p', 'muted-text', '（未提交直接查看）')
    );
  }
  box.append(outcome);

  if (x.reason) {
    const reasonBox = el('div', 'user-reason-box');
    reasonBox.append(el('strong', '', '当时作答思路：'), el('p', '', x.reason));
    box.append(reasonBox);
  }

  // Core Deduction
  const coreExp = el('div', 'core-explanation');
  coreExp.append(el('h4', '', '💡 【核心解题推导与机制】'));
  paragraphs(x.explanation, coreExp);
  box.append(coreExp);

  // Feedback Note / Handout Anchor
  const fb = x.feedback || q.feedback;
  if (fb) {
    if (fb.note) {
      const noteObj = typeof fb.note === 'object' ? fb.note : { text: String(fb.note) };
      const noteCard = el('div', 'feedback-note-card');
      noteCard.append(
        el('h5', '', '✍️ 【建议抄回讲义小记】'),
        el('p', 'handout-note-highlight', noteObj.text)
      );

      const targetSecId = noteObj.topic || fb.targetSection || fb.section;
      if (targetSecId) {
        const jumpBtn = el('button', 'secondary jump-handout-btn', '📖 跳转到讲义对应小节复习');
        jumpBtn.type = 'button';
        jumpBtn.onclick = () => {
          const targetIdx = unit.sections.findIndex(s => s.id === targetSecId);
          if (targetIdx >= 0) {
            navigate(targetIdx);
          }
        };
        noteCard.append(jumpBtn);
      }
      box.append(noteCard);
    }

    // Hot Comment Insights (题库执医高频热评)
    if (fb.commentInsights && fb.commentInsights.length) {
      const commentsBox = el('div', 'hot-comments-box');
      commentsBox.append(el('h5', '', '🔥 【高频热评秒杀提纯】'));
      fb.commentInsights.forEach(c => {
        const item = el('div', 'comment-insight-item');
        if (c.title) item.append(el('strong', 'comment-title', c.title));
        paragraphs(c.text, item);
        commentsBox.append(item);
      });
      box.append(commentsBox);
    }

    // Comparison Table
    if (fb.comparison && fb.comparison.length) {
      const compWrap = el('details', 'comparison-details');
      compWrap.append(
        el('summary', '', '📊 展开对比：选项对照与陷阱区分'),
        makeTable(['选项', '机制影响 / 考点对照', '本题结论'], fb.comparison)
      );
      box.append(compWrap);
    }
  }
}

function makeTable(headers, rows) {
  const wrap = el('div', 'table-wrap');
  const table = el('table', 'teaching-table');
  const head = el('thead');
  const tr = el('tr');
  headers.forEach(t => {
    const th = el('th', '', t);
    th.scope = 'col';
    tr.append(th);
  });
  head.append(tr);
  table.append(head);

  const body = el('tbody');
  rows.forEach(row => {
    const tr = el('tr');
    row.forEach(t => tr.append(rich(el('td'), t)));
    body.append(tr);
  });
  table.append(body);
  wrap.append(table);
  return wrap;
}

function renderMessages() {
  const signature = JSON.stringify([state.messages.map(m => m.id), state.partial]);
  if (signature === lastSignature) return;
  lastSignature = signature;

  const box = $('messages');
  const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 120;
  const oldTop = box.scrollTop;

  box.replaceChildren();
  if (!state.messages.length) {
    box.append(el('div', 'welcome', '你可以直接向 AI 老师提问本节卡点，也可以在左侧讲义中选中一段文字后再提问。'));
  }

  [...state.messages, ...(state.partial ? [{ role: 'assistant', text: state.partial, section: context, partial: true }] : [])].forEach(m => {
    const node = el('div', 'message ' + m.role + (m.partial ? ' partial' : ''));
    const speaker = el('div', 'speaker', m.role === 'user' ? '🙋 你' : m.role === 'assistant' ? '🧑‍🏫 老师' : '⚠️ 错误');
    if (m.section && m.role !== 'error') {
      const back = el('button', 'btn-back-section', '回到对应小节');
      back.onclick = () => {
        const i = unit.sections.findIndex(s => s.id === m.section);
        if (i >= 0) navigate(i);
      };
      speaker.append(back);
    }
    const body = el('div', 'message-body');
    if (m.role === 'assistant') paragraphs(m.text, body);
    else body.textContent = m.text;
    node.append(speaker, body);
    box.append(node);
  });

  box.scrollTop = nearBottom ? box.scrollHeight : oldTop;
}

async function poll() {
  try {
    state = await api('/api/state');
    renderMessages();
    $('answer-status').textContent = state.status || '';
    $('send').disabled = state.busy || !state.liveAvailable;
    if (!state.liveAvailable) {
      $('answer-status').textContent = '实时提问未连接，阅读与做题可正常使用，作答会自动保存。';
    }
    $('save-state').textContent = state.error ? '提问有错误' : state.messages.length ? '学习记录已保存到本机' : '就绪';
  } catch (e) {
    $('save-state').textContent = '与本机断开连接';
  }
}

async function send(e) {
  e.preventDefault();
  const text = $('question-input').value.trim();
  if (!text || state.busy || !state.liveAvailable) return;
  $('send').disabled = true;
  try {
    await api('/api/ask', {
      text,
      section: context,
      question: currentQuestion,
      selection,
      origin: selectedOrigin,
      requestId: crypto.randomUUID()
    });
    $('question-input').value = '';
    await poll();
    $('messages').scrollTop = $('messages').scrollHeight;
  } catch (err) {
    toast(err.message);
    $('send').disabled = false;
  }
}

async function records() {
  await poll();
  const box = $('record-content');
  box.replaceChildren();

  const userMsgs = state.messages.filter(m => m.role === 'user');
  box.append(el('h3', '', `随堂提问 ${userMsgs.length} 次 · 习题作答 ${state.attempts.length} 次 · 全量真题题库 ${unit.questions?.length || 0} 题`));

  // 1. 讲义积累小记 (若用户尚未做题产生个人批注，则动态列出本单元全量真题题眼回写清单)
  const userNotes = state.knowledgeNotes || [];
  if (userNotes.length) {
    box.append(el('h4', '', `📝 我的做题积累小记（已完成 ${userNotes.length} 条）`));
    userNotes.forEach(n => {
      box.append(el('div', 'record-item', n.text));
    });
  }

  // 2. 本单元全部真题考点与讲义回写小记索引（确保用户随时可完整查阅）
  if (unit.questions?.length) {
    box.append(el('h4', '', `📋 本单元全量真题题眼与回写讲义小记（共 ${unit.questions.length} 条）`));
    unit.questions.forEach((q, idx) => {
      const fb = q.feedback?.note;
      if (fb) {
        const nText = typeof fb === 'object' ? fb.text : String(fb);
        const item = el('div', 'record-item');
        item.append(
          el('strong', '', `[${idx + 1}] 【${q.id} · ${q.exam}】`),
          el('p', '', nText)
        );
        box.append(item);
      }
    });
  }

  if (state.attempts?.length) {
    box.append(el('h4', '', '🎯 做题留痕与思路'));
    state.attempts.forEach(a => {
      const q = unit.questions.find(item => item.id === a.question);
      const text = `【${a.question} · ${q?.exam || ''}】作答：${a.choice}（${a.correct ? '正确' : '错误'}）\n思路：${a.reason || '未写思路'}`;
      box.append(el('div', 'record-item', text));
    });
  }

  $('records').showModal();
}

function copyAllNotesAsMarkdown() {
  const lines = [
    `# ${unit.title} · 课程讲义批注与全量真题题眼汇总`,
    `> 导出时间：${new Date().toLocaleString()} · 考研与执考核心干货`,
    '',
    `## 一、课程原讲义各小节手写批注汇总`,
    ''
  ];

  unit.sections.forEach((s, idx) => {
    if (s.type === 'practice' || s.id.includes('practice')) return;
    const note = s.keypoints?.handout_note || '暂无小记';
    lines.push(`### ${String(idx + 1).padStart(2, '0')}. ${s.title}`);
    lines.push(`- **建议抄回讲义**：${note}`);
    if (s.keypoints?.tiantian_mechanism?.length) {
      lines.push(`- **主讲机制点睛**：${s.keypoints.tiantian_mechanism[0]}`);
    }
    if (s.keypoints?.damiao_traps?.length) {
      lines.push(`- **秒杀口诀**：${s.keypoints.damiao_traps[0]}`);
    }
    lines.push('');
  });

  lines.push(`## 二、全量真题题眼与讲义回写批注（全量 ${unit.questions?.length || 0} 题）`);
  lines.push('');
  (unit.questions || []).forEach((q, idx) => {
    const fb = q.feedback?.note;
    if (fb) {
      const nText = typeof fb === 'object' ? fb.text : String(fb);
      lines.push(`${idx + 1}. **【${q.id} · ${q.exam}】**：${nText}`);
    }
  });
  lines.push('');

  lines.push('## 三、错题反思与热评秒杀法');
  lines.push('');
  const wrongAttempts = (state?.attempts || []).filter(a => !a.correct);
  if (wrongAttempts.length) {
    const seen = new Set();
    wrongAttempts.forEach(a => {
      if (seen.has(a.question)) return;
      seen.add(a.question);
      const q = unit.questions.find(item => item.id === a.question);
      if (!q) return;
      lines.push(`### 【${q.id} · ${q.exam}】${q.stem}`);
      lines.push(`- **我的作答**：${a.choice}（错误） | **参考答案**：${q.answer}`);
      if (a.reason) lines.push(`- **当时思考/纠结点**：${a.reason}`);
      lines.push(`- **核心推导**：${q.explanation}`);
      if (q.feedback?.note) {
        const nText = typeof q.feedback.note === 'object' ? q.feedback.note.text : q.feedback.note;
        lines.push(`- **讲义回写**：${nText}`);
      }
      lines.push('');
    });
  } else {
    lines.push('当前暂无做错题目记录。');
    lines.push('');
  }

  const fullText = lines.join('\n');
  navigator.clipboard.writeText(fullText).then(() => {
    toast('📋 已将全部讲义批注与错题总结复制到剪贴板，可直接粘贴到 Obsidian 笔记中！');
  }).catch(() => {
    toast('复制到剪贴板失败，请手动选择复制');
  });
}

function initQuickChips() {
  const chipsBox = $('quick-chips');
  if (!chipsBox) return;
  chipsBox.replaceChildren();
  const presets = unit.quickChips || [];
  presets.forEach(txt => {
    const btn = el('button', 'chip-btn', txt);
    btn.type = 'button';
    btn.onclick = () => {
      $('question-input').value = txt;
      $('question-input').focus();
    };
    chipsBox.append(btn);
  });
}

async function loadUnit(unitId) {
  try {
    currentUnitId = unitId;
    const url = new URL(window.location);
    url.searchParams.set('unit', unitId);
    window.history.replaceState({}, '', url);

    if ($('unit-switcher')) {
      $('unit-switcher').value = unitId;
    }

    [unit, state] = await Promise.all([
      api('/api/unit'),
      api('/api/state')
    ]);

    // 更新页面标题和左侧导览元信息
    document.title = `${unit.title} · 课程原讲义伴随教辅`;
    if ($('unit-title')) $('unit-title').textContent = unit.title;
    if ($('unit-eyebrow')) {
      $('unit-eyebrow').textContent = unit.metadata?.lecture || '';
    }
    if ($('unit-meta')) {
      $('unit-meta').textContent = unit.metadata?.pages || '';
    }
    if ($('stage')) {
      $('stage').textContent = unit.stage || '课程原讲义完整版 · 伴随干货与三梯队习题';
    }

    // 重置当前小节位置
    current = 0;
    context = unit.sections[0]?.id || 'nature';

    // Mind Map Entry in Outline
    $('unit-map-nav-btn')?.remove();
    const mapBtn = el('button', 'unit-map-btn');
    mapBtn.id = 'unit-map-nav-btn';
    mapBtn.type = 'button';
    const systemLabel = unit.overview?.systemLabel || '全局';
    mapBtn.append(
      el('span', 'map-title', `🗺️ 导图先行 · ${systemLabel}思维导图`),
      el('span', 'map-subtitle', '全局坐标 · 疾病串联 · 随时对照')
    );
    mapBtn.onclick = () => renderOverview();
    $('toc').before(mapBtn);

    // Build TOC
    const toc = $('toc');
    toc.replaceChildren();
    let group = '';
    unit.sections.forEach((s, i) => {
      if (s.group !== group) {
        group = s.group;
        toc.append(el('h3', 'toc-group', group));
      }
      const b = el('button');
      b.dataset.section = s.id;
      b.append(
        el('span', 'toc-title', `${String(i + 1).padStart(2, '0')} ${s.title}`),
        el('span', 'toc-subtitle', s.subtitle)
      );
      b.onclick = () => navigate(i);
      toc.append(b);
    });

    // Check Hash
    const hash = location.hash.slice(1);
    if (hash === 'overview') {
      renderOverview(false);
    } else {
      let targetIdx = unit.sections.findIndex(s => s.id === hash);
      if (hash.startsWith('quiz-')) {
        targetIdx = unit.sections.findIndex(s => s.id.includes('practice') || s.type === 'practice');
      }
      if (targetIdx >= 0) current = targetIdx;
      renderLesson();
    }
    initQuickChips();
    renderMessages();
  } catch (e) {
    $('lesson').textContent = '加载失败：' + e.message;
  }
}

async function init() {
  try {
    // Setup Companion Tab Listeners
    $('tab-points').onclick = () => switchCompanionTab('points');
    $('tab-ask').onclick = () => switchCompanionTab('ask');

    // Populate Unit Switcher from /api/units
    let units = [];
    try {
      units = await api('/api/units');
      const switcher = $('unit-switcher');
      if (!currentUnitId && units.length) currentUnitId = units[0].id;
      if (switcher && units.length) {
        switcher.replaceChildren();
        units.forEach(u => {
          const opt = el('option', '', `${u.title} (${u.lecture.split('·')[1]?.trim() || u.id})`);
          opt.value = u.id;
          switcher.append(opt);
        });
        switcher.value = currentUnitId;
        switcher.onchange = () => loadUnit(switcher.value);
      }
    } catch (e) {
      console.warn('Load units error', e);
    }

    if (!currentUnitId) {
      $('lesson').textContent = '未发现已注册单元，请先检查 UNIT_REGISTRY 与单元 JSON。';
      return;
    }
    await loadUnit(currentUnitId);
    await poll();
    setInterval(poll, 2500);
  } catch (e) {
    $('lesson').textContent = '初始化失败：' + e.message;
  }
}

// Global button handlers
$('previous').onclick = () => navigate(current - 1);
$('next').onclick = () => navigate(current + 1);
$('ask-form').onsubmit = send;
$('question-input').onkeydown = e => {
  if (e.ctrlKey && e.key === 'Enter') send(e);
};
$('record-toggle').onclick = records;
$('close-records').onclick = () => $('records').close();
$('copy-markdown-btn').onclick = copyAllNotesAsMarkdown;

// Text selection listener on reading article
$('reading').addEventListener('mouseup', () => {
  const sel = window.getSelection();
  const text = sel.toString().trim();
  if (text && $('reading').contains(sel.anchorNode)) {
    setContext(unit.sections[current].id, null, text.slice(0, 2000));
  }
});

init();
