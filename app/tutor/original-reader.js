import {getDocument,GlobalWorkerOptions,TextLayer} from './vendor/pdfjs/build/pdf.mjs';
GlobalWorkerOptions.workerSrc='/vendor/pdfjs/build/pdf.worker.mjs';
const documents=new Map();
const node=(tag,cls,text)=>{const e=document.createElement(tag);e.className=cls||'';if(text!==undefined)e.textContent=text;return e;};
function button(text,fn){const b=node('button','secondary',text);b.type='button';b.onclick=fn;return b;}

export async function mount(host,options){
  const {sourceId,source,topic,api,notify,onAsk,unit}=options;
  const unitParam = unit ? `?unit=${encodeURIComponent(unit)}` : '';
  const docKey = unit ? `${unit}:${sourceId}` : sourceId;
  const pdfUrl = `/source/${encodeURIComponent(sourceId)}${unitParam}`;
  const pages=options.pages||(options.page?[options.page]:[1]);
  let zoom=1,boxMode=false,pending=null,disposed=false,renderId=0;

  const bar=node('div','original-toolbar');
  const label=node('strong','',`${source.label} · 共 ${pages.length} 页 (${pages.map(p=>'P'+p).join(', ')})`);
  const zoomSelect=node('select');zoomSelect.setAttribute('aria-label','讲义缩放');
  for(const [value,text] of [[1,'适应宽度'],[1.2,'放大 120%'],[1.4,'放大 140%']]){
    const o=node('option','',text);o.value=value;zoomSelect.append(o);
  }
  zoomSelect.onchange=()=>{zoom=Number(zoomSelect.value);renderAll();};
  const boxToggle=button('框选提问',()=>{
    boxMode=!boxMode;
    scroll.querySelectorAll('.original-page').forEach(f=>f.classList.toggle('box-mode',boxMode));
    boxToggle.setAttribute('aria-pressed',String(boxMode));
    notify(boxMode?'已开启框选模式，可在讲义上拖动框选提问。':'已退出框选模式，可正常选中文字。');
  });
  const originalLink=node('a','','打开原 PDF');originalLink.target='_blank';originalLink.rel='noopener';
  originalLink.href=`/source/${encodeURIComponent(sourceId)}${unitParam}${pages[0]?'#page='+pages[0]:''}`;
  bar.append(label,zoomSelect,boxToggle,originalLink);

  const selectionBar=node('div','selection-toolbar');selectionBar.hidden=true;
  const selectedLabel=node('span','selected-preview'),noteInput=node('input');
  noteInput.placeholder='写一句自己的划线笔记（可选）';noteInput.setAttribute('aria-label','勾画补充');
  const save=button('保存勾画',async()=>{
    if(!pending)return;save.disabled=true;
    try{
      await api('/api/annotation',{...pending,note:noteInput.value});
      pending=null;selectionBar.hidden=true;noteInput.value='';
      window.getSelection()?.removeAllRanges();
      await refreshMarks();
      notify('勾画已保存到本机。');
    }catch(e){notify(e.message);}finally{save.disabled=false;}
  });
  const ask=button('就此提问',()=>{if(pending){onAsk(pending);selectionBar.hidden=true;}});
  selectionBar.append(selectedLabel,noteInput,save,ask,button('取消',()=>{pending=null;selectionBar.hidden=true;}));

  const scroll=node('div','original-scroll');
  const markList=node('div','page-note-list');
  host.append(bar,selectionBar,scroll,markList);

  let resizeTimer=null;
  let isRendering=false;
  host.dispose=()=>{disposed=true;renderId++;clearTimeout(resizeTimer);resize.disconnect();};
  const resize=new ResizeObserver(()=>{
    clearTimeout(resizeTimer);
    resizeTimer=setTimeout(()=>{
      if(disposed||isRendering)return;
      const curW=host.clientWidth||800;
      // 阈值加大到 30px，彻底消除滚动条出现/消失导致 15~17px 抖动而陷入重绘死循环
      if(Math.abs(lastWidth-curW)>30){
        renderAll();
      }
    },250);
  });
  let lastWidth=0;resize.observe(host);

  if(!documents.has(docKey)){
    documents.set(docKey,getDocument({
      url: pdfUrl,
      cMapUrl:'/vendor/pdfjs/web/cmaps/',cMapPacked:true,
      standardFontDataUrl:'/vendor/pdfjs/web/standard_fonts/',
      wasmUrl:'/vendor/pdfjs/web/wasm/',isEvalSupported:false
    }).promise);
  }

  let pdf;
  try{
    pdf=await documents.get(docKey);
    if(!disposed)await renderAll();
  }catch(e){
    if(!disposed){scroll.textContent='原讲义加载失败：'+e.message;notify('原讲义加载失败：'+e.message);}
  }

  function capture(pageNo,rects,quote){
    pending={sourceId,sourceVersion:source.fingerprint,page:pageNo,topic,rects,quote};
    selectedLabel.textContent=quote?`选中 (P${pageNo}): ${quote.slice(0,80)}`:`框选区域 (P${pageNo})`;
    selectionBar.hidden=false;
  }

  async function renderAll(){
    if(!pdf||disposed||isRendering)return;
    isRendering=true;
    const token=++renderId;
    lastWidth=host.clientWidth||800;
    
    try{
      scroll.replaceChildren();

      for(const pageNo of pages){
        if(pageNo<1||pageNo>pdf.numPages)continue;
        const bookPage = source.bookStart ? (source.bookStart + pageNo - 1) : null;
        const badgeText = bookPage ? `${source.label} · 第 ${pageNo} 页 (书页 ${bookPage})` : `${source.label} · 第 ${pageNo} 页`;
        const pageHeader=node('div','page-divider-badge',badgeText);
        const frame=node('div','original-page');frame.dataset.page=String(pageNo);
        frame.style.minHeight='380px';
        if(boxMode)frame.classList.add('box-mode');
        const canvas=node('canvas'),textLayer=node('div','textLayer'),marks=node('div','page-marks'),dragLayer=node('div','drag-layer');
        frame.append(canvas,textLayer,marks,dragLayer);
        scroll.append(pageHeader,frame);

        try{
          const pg=await pdf.getPage(pageNo);
          if(token!==renderId||disposed)return;
          const availableW=Math.max(300,lastWidth-24);
          const unscaledVp=pg.getViewport({scale:1});
          const scale=(availableW/unscaledVp.width)*zoom;
          const vp=pg.getViewport({scale});

          frame.style.width=vp.width+'px';
          frame.style.height=vp.height+'px';
          frame.style.minHeight='auto';
          frame.style.setProperty('--total-scale-factor',String(scale));
          frame.style.setProperty('--scale-factor',String(scale));

          const ratio=Math.min(window.devicePixelRatio||1,2);
          canvas.width=Math.floor(vp.width*ratio);
          canvas.height=Math.floor(vp.height*ratio);
          canvas.style.width=vp.width+'px';
          canvas.style.height=vp.height+'px';

          const ctx=canvas.getContext('2d');
          const activeRender=pg.render({
            canvasContext:ctx,viewport:vp,
            transform:ratio===1?null:[ratio,0,0,ratio,0,0]
          });
          await activeRender.promise;
          if(token!==renderId||disposed)return;

          textLayer.replaceChildren();
          const textContent=await pg.getTextContent();
          await new TextLayer({textContentSource:textContent,container:textLayer,viewport:vp}).render();
        }catch(e){
          console.error('Render page error',pageNo,e);
        }

      // Mouse selection on textLayer
      frame.addEventListener('mouseup',()=>{
        if(boxMode)return;
        const sel=window.getSelection();
        if(!sel?.rangeCount||!sel.toString().trim()||!textLayer.contains(sel.anchorNode)||!textLayer.contains(sel.focusNode))return;
        const r=frame.getBoundingClientRect();
        const rects=[...sel.getRangeAt(0).getClientRects()].filter(a=>a.width>1&&a.height>1).map(a=>{
          const x=Math.max(0,(a.left-r.left)/r.width),y=Math.max(0,(a.top-r.top)/r.height);
          return [x,y,Math.min(a.width/r.width,1-x),Math.min(a.height/r.height,1-y)];
        }).filter(a=>a[2]>0&&a[3]>0).slice(0,200);
        if(rects.length)capture(pageNo,rects,sel.toString().slice(0,4000));
      });

      // Pointer drag for boxMode
      let drag=null;
      frame.addEventListener('pointerdown',e=>{
        if(!boxMode)return;e.preventDefault();
        frame.setPointerCapture(e.pointerId);drag={x:e.clientX,y:e.clientY};
      });
      frame.addEventListener('pointermove',e=>{
        if(!drag)return;const r=frame.getBoundingClientRect();
        dragLayer.style.cssText=`left:${Math.min(drag.x,e.clientX)-r.left}px;top:${Math.min(drag.y,e.clientY)-r.top}px;width:${Math.abs(e.clientX-drag.x)}px;height:${Math.abs(e.clientY-drag.y)}px`;
        dragLayer.hidden=false;
      });
      frame.addEventListener('pointerup',e=>{
        if(!drag)return;const r=frame.getBoundingClientRect(),clamp=v=>Math.max(0,Math.min(1,v));
        const x=clamp((Math.min(drag.x,e.clientX)-r.left)/r.width),y=clamp((Math.min(drag.y,e.clientY)-r.top)/r.height);
        const w=Math.min(Math.abs(e.clientX-drag.x)/r.width,1-x),h=Math.min(Math.abs(e.clientY-drag.y)/r.height,1-y);
        drag=null;dragLayer.hidden=true;
        if(w>.005&&h>.005)capture(pageNo,[[x,y,w,h]],'');
      });
    }
    await refreshMarks();
  }finally{
    isRendering=false;
  }
}

  async function refreshMarks(){
    const state=await api('/api/state');if(disposed)return;
    markList.replaceChildren();
    const items=[...(state.annotations||[]),...(state.knowledgeNotes||[])].filter(n=>n.sourceId===sourceId&&pages.includes(n.page));
    
    // Clear marks on all pages
    scroll.querySelectorAll('.page-marks').forEach(m=>m.replaceChildren());

    if(items.length>0){
      const head=node('div','page-note-header');
      head.append(
        node('span','page-note-title',`📌 本节对应讲义批注与真题提纯（共 ${items.length} 条）`),
        node('span','page-note-hint','做题考点已按页码精准映射回对应小节')
      );
      markList.append(head);
    }

    for(const n of items){
      const frame=scroll.querySelector(`.original-page[data-page="${n.page}"]`);
      if(!frame)continue;
      const marks=frame.querySelector('.page-marks');
      const valid=n.sourceVersion===source.fingerprint,wrong=!!n.everWrong,personal=!!n.rects;
      if(!n.deleted&&valid&&marks){
        for(const rect of n.rects||[[0.965,0.015,0.02,0.015]]){
          if(!rect)continue;
          const m=node('div','page-mark '+(wrong?'was-wrong':personal?'personal':'from-question'));
          const [x,y,w,h]=rect;
          m.style.cssText=`left:${x*100}%;top:${y*100}%;width:${w*100}%;height:${h*100}%`;
          m.title=n.note||n.text||n.quote||'';
          marks.append(m);
        }
      }
      const row=node('div','saved-note '+(wrong?'was-wrong':'')+(n.deleted?' withdrawn':''));
      row.append(node('span','note-label',wrong?'曾错 · 积累':personal?'我的勾画':'真题考点'));
      row.append(node('p','',n.note||n.text||n.quote||'原页标注'));
      row.append(button(n.deleted?'恢复':'撤销',async()=>{
        try{await api('/api/annotation-status',{id:n.id,deleted:!n.deleted});await refreshMarks();}
        catch(e){notify(e.message);}
      }));
      markList.append(row);
    }
  }

  return {refreshMarks,dispose:host.dispose,jump:page=>{
    const f=scroll.querySelector(`.original-page[data-page="${page}"]`);
    f?.scrollIntoView({behavior:'smooth',block:'start'});
  }};
}
