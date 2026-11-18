#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
verify_unit.py: 医学伴学教辅新章节全自动验收门禁 (Pre-flight Verification Gate)

只使用 ASCII 状态标记，避免默认 Windows GBK 控制台因 emoji 触发
UnicodeEncodeError。门禁会在进程内启动一个临时服务，不依赖 8766 是否已有进程。
"""

import http.client
import json
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = next(parent for parent in HERE.parents if (parent / "AGENTS.md").is_file())


def log_pass(msg):
    print(f"  [PASS] {msg}")


def log_fail(msg):
    print(f"  [FAIL] {msg}")


def _section_pages(section):
    original = section.get("original") or {}
    pages = original.get("pages")
    if isinstance(pages, list) and pages:
        return pages
    page = original.get("page")
    return [page] if isinstance(page, int) else []


def verify_unit_data(unit_id, unit_path):
    print(f"\n>>> 1. 检查单元数据结构与字段完整性 [{unit_id} -> {unit_path.name}]")
    if not unit_path.is_file():
        log_fail(f"单元 JSON 文件不存在：{unit_path}")
        return False

    try:
        data = json.loads(unit_path.read_text(encoding="utf-8"))
    except Exception as e:
        log_fail(f"JSON 解析失败：{e}")
        return False

    errors = []

    for field in ("id", "title", "metadata", "overview", "sections", "sources", "questions"):
        if field not in data:
            errors.append(f"缺少顶层关键字段: {field}")

    sections = data.get("sections", [])
    if not sections:
        errors.append("sections 列表为空")
    sec_by_id = {s.get("id"): s for s in sections if s.get("id")}

    sources = data.get("sources", {})
    if "tt-handout" not in sources:
        errors.append("sources 缺少主讲义 tt-handout")
    map_source = (data.get("overview") or {}).get("sourceId")
    if not map_source:
        errors.append("overview 缺少 sourceId")
    elif map_source not in sources:
        errors.append(f"overview.sourceId '{map_source}' 不在 sources 中")
    for skey, sval in sources.items():
        if sval.get("kind") == "pdf":
            p = ROOT / sval.get("path", "")
            if not p.is_file():
                errors.append(f"来源 {skey} 本地 PDF 文件不存在: {p}")
            if skey in ("tt-handout", map_source) and "bookStart" not in sval:
                errors.append(f"来源 {skey} 必须包含起始书页 bookStart 字段")

    overview = data.get("overview") or {}
    if not overview.get("sourceId"):
        errors.append("overview 缺少 sourceId")
    elif overview.get("sourceId") not in sources:
        errors.append(f"overview.sourceId '{overview['sourceId']}' 不在 sources 中")
    for key in ("mapPage", "mapBookPage"):
        if not isinstance(overview.get(key), int):
            errors.append(f"overview 缺少整数 {key}")

    questions = data.get("questions", [])
    if not questions:
        errors.append("questions 列表为空 (无任何真题入库)")

    seen_ids = set()
    seen_qids = set()
    tier_counts = {"tier1": 0, "tier2": 0, "tier3": 0}
    for idx, q in enumerate(questions):
        qid = q.get("id")
        if not qid:
            errors.append(f"第 {idx + 1} 题缺少 id")
            continue
        if qid in seen_ids:
            errors.append(f"存在重复题目 id: {qid}")
        seen_ids.add(qid)

        source_qid = q.get("qid")
        if not source_qid:
            errors.append(f"题目 {qid} 缺少 qid（源题号/稳定题号）")
        elif source_qid in seen_qids:
            errors.append(f"存在重复源题号 qid: {source_qid}（题目 {qid}）")
        else:
            seen_qids.add(source_qid)

        tier = q.get("tier")
        if tier not in tier_counts:
            errors.append(f"题目 {qid} 包含非法梯队分类: {tier}")
        else:
            tier_counts[tier] += 1

        if not q.get("stem"):
            errors.append(f"题目 {qid} 题干 stem 为空")
        options = q.get("options", [])
        if len(options) < 3:
            errors.append(f"题目 {qid} 选项 options 少于 3 项")
        option_keys = {o.get("key") for o in options}
        if not q.get("answer"):
            errors.append(f"题目 {qid} 答案 answer 为空")
        else:
            answer = str(q.get("answer"))
            if any(k not in option_keys for k in answer):
                errors.append(f"题目 {qid} 答案 {answer} 含不在选项 {sorted(option_keys)} 中的字符")
        if not q.get("explanation"):
            errors.append(f"题目 {qid} 解析 explanation 为空")
        if not q.get("exam"):
            errors.append(f"题目 {qid} 缺少 exam")
        if not q.get("tierLabel"):
            errors.append(f"题目 {qid} 缺少 tierLabel")

        fb = q.get("feedback", {})
        if not fb.get("note"):
            errors.append(f"题目 {qid} 缺少建议抄回讲义小记 feedback.note")
        if not fb.get("derivation"):
            errors.append(f"题目 {qid} 缺少 feedback.derivation")
        if tier == "tier2" and not isinstance(fb.get("commentInsights"), list):
            errors.append(f"题目 {qid} 缺少 feedback.commentInsights 列表")

        target_sec = fb.get("targetSection")
        if not target_sec:
            errors.append(f"题目 {qid} 缺少 feedback.targetSection")
        elif target_sec not in sec_by_id:
            errors.append(f"题目 {qid} 关联的 targetSection '{target_sec}' 不在 sections 列表中")
        else:
            target_page = fb.get("targetPage")
            pages = _section_pages(sec_by_id[target_sec])
            if not isinstance(target_page, int) or target_page not in pages:
                errors.append(f"题目 {qid} 的 targetPage {target_page} 不在目标小节页码 {pages} 中")

    expected_tier1 = (data.get("metadata") or {}).get("tier1Expected", 8)
    if not isinstance(expected_tier1, int) or expected_tier1 < 1:
        expected_tier1 = 8
    if tier_counts["tier1"] != expected_tier1:
        errors.append(f"tier1 必须为 {expected_tier1} 题（主讲课后题），当前 {tier_counts['tier1']} 题")
    if tier_counts["tier2"] < 1:
        errors.append("tier2 不能为空（执医题全量）")
    if tier_counts["tier3"] < 1:
        errors.append("tier3 不能为空（考研题全量）")

    if errors:
        for err in errors[:12]:
            log_fail(err)
        if len(errors) > 12:
            log_fail(f"... 剩余 {len(errors) - 12} 项错误已省略")
        return False

    log_pass(
        f"数据规范核验通过 (共 {len(questions)} 题：主讲课后 {tier_counts['tier1']} 题"
        f" + 执医 {tier_counts['tier2']} 题 + 考研 {tier_counts['tier3']} 题)"
    )
    return True


def start_test_server():
    """Start an isolated in-process server with temporary session data."""
    import server as srv

    class NullAgent:
        def close(self):
            pass

    tmp = tempfile.TemporaryDirectory(prefix="tutor-gate-")
    apps = {}
    for uid, udata in srv.UNITS.items():
        sfile = "session.json" if uid == srv.DEFAULT_UNIT_ID else f"session_{uid}.json"
        apps[uid] = srv.Application(tmp.name, agent=NullAgent(), session_filename=sfile, unit_data=udata)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.make_handler(apps, 0))
    port = httpd.server_address[1]
    httpd.RequestHandlerClass = srv.make_handler(apps, port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, tmp, f"http://127.0.0.1:{port}", port


def _get(opener, url, port, headers=None):
    h = {"Host": f"127.0.0.1:{port}"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    return opener.open(req, timeout=8)


def verify_server_endpoints(unit_id, base_url, port):
    print(f"\n>>> 2. 检查服务 API、字段完整性与单元隔离 [{unit_id}]")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    try:
        with _get(opener, f"{base_url}/?unit={unit_id}", port, {"Sec-Fetch-Site": "cross-site"}) as resp:
            if resp.status != 200 or len(resp.read()) < 1000:
                log_fail(f"顶层页面异常: {resp.status}")
                return False
            log_pass("顶层页面跨站打开正常 (200 OK，非 403)")
    except Exception as e:
        log_fail(f"服务无法连通或拦截页面: {e}")
        return False

    try:
        with _get(opener, f"{base_url}/api/unit?unit={unit_id}", port) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        qs = data.get("questions", [])
        if not qs:
            log_fail("/api/unit 返回的题目为空")
            return False
        broken = [
            q.get("id") for q in qs
            if not q.get("answer") or not q.get("explanation") or not (q.get("feedback") or {}).get("note")
        ]
        if broken:
            log_fail(f"/api/unit 剥离字段的题目: {broken[:5]}（共 {len(broken)} 题）")
            return False
        log_pass(f"/api/unit 全量透传题解与讲义小记 ({len(qs)} 题)")
    except Exception as e:
        log_fail(f"/api/unit 请求失败: {e}")
        return False

    sources = data.get("sources", {})
    map_source = (data.get("overview") or {}).get("sourceId")
    for key in dict.fromkeys(["tt-handout", map_source]):
        source = sources.get(key)
        if not source or source.get("kind") != "pdf":
            continue
        try:
            with _get(opener, f"{base_url}/source/{key}?unit={unit_id}", port) as resp:
                raw = resp.read()
                if resp.status != 200 or not raw.startswith(b"%PDF"):
                    log_fail(f"PDF 流异常: {key} status={resp.status}")
                    return False
                log_pass(f"PDF 流正常: {key} ({len(raw)} 字节)")
        except Exception as e:
            log_fail(f"PDF 流请求失败: {key}: {e}")
            return False

    # 未登记 unit 必须 404，而不是静默回退到默认单元
    unknown = "__gate_unknown_unit__"
    try:
        _get(opener, f"{base_url}/api/unit?unit={unknown}", port)
        log_fail("未知 unit 未返回 404（发生静默回退）")
        return False
    except urllib.error.HTTPError as e:
        if e.code != 404:
            log_fail(f"未知 unit 返回 {e.code}，期望 404")
            return False
        log_pass("未知 unit 正确返回 404")
    except Exception as e:
        log_fail(f"未知 unit 探针失败: {e}")
        return False

    # 未登记 source 必须 404，不能跨 unit 借 PDF
    candidate = next((k for k in ("physiology", "pathology-immune", "volumes") if k not in sources), None)
    if candidate:
        try:
            _get(opener, f"{base_url}/source/{candidate}?unit={unit_id}", port)
            log_fail(f"未登记 source {candidate} 未返回 404（发生跨单元回退）")
            return False
        except urllib.error.HTTPError as e:
            if e.code != 404:
                log_fail(f"未登记 source 返回 {e.code}，期望 404")
                return False
            log_pass(f"未登记 source 正确返回 404: {candidate}")
        except Exception as e:
            log_fail(f"未登记 source 探针失败: {e}")
            return False

    # 写入接口必须拒绝外部 Origin
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        body = json.dumps({"section": "__gate__"}, ensure_ascii=False).encode("utf-8")
        conn.request(
            "POST",
            f"/api/position?unit={unit_id}",
            body=body,
            headers={
                "Host": f"127.0.0.1:{port}",
                "Origin": "https://evil.example",
                "Content-Type": "application/json",
            },
        )
        resp = conn.getresponse()
        status = resp.status
        resp.read()
        conn.close()
        if status != 403:
            log_fail(f"外部 Origin 写入返回 {status}，期望 403")
            return False
        log_pass("外部 Origin 写入正确返回 403")
    except Exception as e:
        log_fail(f"外部 Origin 写入探针失败: {e}")
        return False

    return True


def verify_shortcuts(unit_id):
    print(f"\n>>> 3. 检查学习工具双击入口与快捷方式 [{unit_id}]")
    tools_dir = ROOT / "学习工具"
    html_entry = tools_dir / "医学伴学教辅.html"
    cmd_entry = tools_dir / "打开呼吸系统医学伴学教辅.cmd"

    if not html_entry.is_file() or html_entry.stat().st_size < 200:
        log_fail(f"学习工具 HTML 入口缺失或内容为空：{html_entry}")
        return False
    html_text = html_entry.read_text(encoding="utf-8", errors="replace")
    if "127.0.0.1" not in html_text or "http" not in html_text:
        log_fail("HTML 入口没有可用的本机 URL")
        return False
    log_pass("HTML 双击入口存在且包含本机 URL")

    if not cmd_entry.is_file() or cmd_entry.stat().st_size < 100:
        log_fail(f"学习工具 CMD 入口缺失或内容为空：{cmd_entry}")
        return False
    cmd_text = cmd_entry.read_text(encoding="utf-8", errors="replace")
    if "launch" not in cmd_text.lower() and "server.py" not in cmd_text.lower():
        log_fail("CMD 入口没有指向 launch.py/server.py")
        return False
    log_pass("CMD 守护入口存在且指向 Python 启动器")

    url_files = list(tools_dir.glob("*.url"))
    matched = [p for p in url_files if f"unit={unit_id}" in p.read_text(encoding="utf-8", errors="replace")]
    if not matched:
        log_fail(f"学习工具缺少 unit={unit_id} 的 .url 快捷方式")
        return False
    log_pass(f"快捷方式存在: {matched[0].name}")
    return True


def main():
    target_unit = sys.argv[1] if len(sys.argv) > 1 else "pte"

    from server import UNIT_REGISTRY
    if target_unit not in UNIT_REGISTRY:
        print(f"[FAIL] 目标单元 '{target_unit}' 未在 server.py 的 UNIT_REGISTRY 中注册")
        sys.exit(1)

    unit_file = UNIT_REGISTRY[target_unit]
    print("=" * 65)
    print(" 医学伴学教辅 · 自动化全景门禁核验 (Pre-flight Gate)")
    print(f" 目标单元：{target_unit} -> {unit_file.name}")
    print("=" * 65)

    try:
        httpd, tmp, base_url, port = start_test_server()
    except Exception as e:
        print(f"[FAIL] 无法启动临时验证服务: {e}")
        sys.exit(1)

    try:
        ok1 = verify_unit_data(target_unit, unit_file)
        ok2 = verify_server_endpoints(target_unit, base_url, port)
        ok3 = verify_shortcuts(target_unit)
    finally:
        try:
            httpd.shutdown()
            httpd.server_close()
        finally:
            tmp.cleanup()

    print("\n" + "=" * 65)
    if ok1 and ok2 and ok3:
        print("  [OK] 全部门禁核验通过。")
        print("=" * 65)
        sys.exit(0)
    else:
        print("  [FAIL] 存在未通过项，请先根据上述失败日志修复。")
        print("=" * 65)
        sys.exit(1)


if __name__ == "__main__":
    main()
