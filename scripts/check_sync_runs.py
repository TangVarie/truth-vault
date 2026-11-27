#!/usr/bin/env python3
"""Completed-scan regressions using the real ingestion main and in-memory I/O.

SQL transaction/concurrent completion behavior is separately exercised by
check_sync_runs.sql against PostgreSQL in CI. No external clients are used.

D-153 additions:
  · v1.25 not applied (missing RPC) → the sync ingests exactly as before v1.25 (old stamp-based
    reconciliation), warns once, scan_completed=0; a transient begin error is NOT "apply the migration";
  · metric / account write failures do not block scan completion (they still turn the run red);
  · the source-level guards of the removed COR-011 CI block that had no behavioural replacement
    (report-only reconciliation, downstream impact list, first-deploy list in scripts/README.md).

11-26 补 (check_feishu_client): 真的 FeishuClient 对着假的 requests.get / post 跑 —— 11-26 夜跑 WTG 第 5 页 HTTP 400,
日志里只有 requests 的「400 Client Error … for url: …」, 飞书的 code / msg 丢了, URL 里的 app_token 进了公开日志。
钉住: 先读 code 再定重不重试 (没见过的 400 同一页只再试一次、429 按回包头等、5xx 退避、401 刷一次 token、
重试也一样错的 code 立刻报), 报错文本里有 状态码 · code · msg · 第几页, 没有 URL / app_token / page_token。
F12 走真的 main() 和不打码的 StreamHandler: 文本在源头就干净, 不是靠 formatter 打码。
F13 (复审补): code=0 可回包没有 data 等形状不对 → 报、整轮红、不对账, 不当空页 (老代码在这上面也是抛的)。
F14 (复审补): 读超时、刷 token 不占次数、view_id 掩掉、log_id 不像 id 不写、5xx 带 code=0 不算成功。
"""
from __future__ import annotations

import contextlib
import inspect
import io
import json
import logging
import os
import pathlib
import sys
import traceback
from unittest.mock import patch

import requests

import sync_feishu_notes_to_truth_vault as sync


class Query:
    def __init__(self, db, table):
        self.db, self.table = db, table
    def __getattr__(self, name):
        return lambda *a, **k: self


class Database:
    def __init__(self):
        self.runs, self.notes, self.presence = {}, {}, {}
        self.fail_writes = set()
        self.fail_begin = self.fail_complete = False   # fail_begin: False | 'missing' | 'transient'
        self.legacy_reads = 0
    def schema(self, name):
        return self
    def table(self, name):
        return Query(self, name)
    def rpc(self, name, payload):
        def execute():
            run_id = payload['p_run_id']
            if name == 'begin_note_sync':
                if self.fail_begin == 'missing':
                    raise RuntimeError("{'code': 'PGRST202', 'message': 'Could not find the function "
                                       "truth_vault.begin_note_sync(p_project_id, p_run_id) in the schema cache'}")
                if self.fail_begin:
                    raise RuntimeError('synthetic connection reset by peer')
                self.runs[run_id] = dict(seq=len(self.runs)+1, completed=False)
            elif name == 'complete_note_sync':
                if self.fail_complete:
                    raise RuntimeError('injected completion rollback')
                run = self.runs[run_id]
                for note_id in set(payload['p_note_ids']) | set(payload.get('p_seen_failed_note_ids', [])):
                    self.presence[note_id] = max(run['seq'], self.presence.get(note_id, 0))
                run['completed'] = True
            else:
                raise AssertionError(name)
            return type('Response', (), {'data': 1})()
        return type('RPC', (), {'execute': staticmethod(execute)})()
    def write(self, _, notes, **kwargs):
        written = set()
        for note in notes:
            if note['note_id'] not in self.fail_writes:
                self.notes[note['note_id']] = dict(note)
                written.add(note['note_id'])
        return written
    def vanished(self):
        latest = max((r['seq'] for r in self.runs.values() if r['completed']), default=0)
        return {n for n, seq in self.presence.items() if seq < latest}
    def pages(self, query, **kwargs):
        if query.table == 'v_notes_vanished':
            return [dict(note_id=n, last_seen_run_id='completed', tier='趴') for n in sorted(self.vanished())]
        if query.table == 'notes' and self.fail_begin == 'missing':
            # The pre-v1.25 reconciliation reads the per-note stamps straight from notes.
            self.legacy_reads += 1
            return [dict(note_id='AUDIT_gone', tier='趴', last_seen_run_id='an-older-run', last_seen_at='2000-01-01T00:00:00+00:00'),
                    dict(note_id='AUDIT_never', tier='趴', last_seen_run_id=None, last_seen_at=None)]
        return []
    def completed(self):
        return sum(r['completed'] for r in self.runs.values())


LAST_LOG = ['']


def run(db, ids, *args, fetch_fail=False, fail_records=(), metrics=(0, []), accounts=(), feishu=None,
        app_token='synthetic'):
    """feishu / app_token (11-26 补): 传真的 sync.FeishuClient 和一个假 app_token, 看报错进日志时带不带它。"""
    class Feishu:
        def __init__(self, *a): pass
        def list_records(self, *a):
            for note_id in ids:
                yield dict(record_id=note_id, fields={'body': 'synthetic'})
            if fetch_fail:
                raise RuntimeError('injected later-page failure')
    mapping = dict(project_id='AUDIT', platform='xiaohongshu', field_mapping={'body': 'raw_content'},
                   sync_config={'feishu_app_token': app_token, 'feishu_table_id': 'synthetic'})
    def transform(_, record_id, fields):
        if record_id in fail_records:
            raise ValueError('synthetic malformed observed row')
        return dict(note_id='AUDIT_'+record_id, project_id='AUDIT', raw_content='synthetic'), None, []
    mocks = dict(FeishuClient=feishu or Feishu, get_supabase_client=lambda: db,
                 load_mapping=lambda _: mapping, assert_db_schema_ready=lambda _: None,
                 ensure_project_exists=lambda *a: None, fetch_acknowledged_quarantine=lambda *a: set(),
                 ensure_accounts_batch=lambda *a, **k: list(accounts), upsert_notes_batch=db.write,
                 upsert_metrics_batch=lambda *a, **k: metrics, update_project_date_range=lambda *a: None,
                 _detect_missing_core_columns=lambda *a: [], _detect_missing_capabilities=lambda *a: [],
                 _current_tiers=lambda *a: {}, risk_source_columns=lambda *a: {},
                 prepare_content_layer=lambda *a: True, transform_row=transform, fetch_all_pages=db.pages)
    log = io.StringIO()
    handler = logging.StreamHandler(log)
    old_handlers = list(sync.logger.handlers)
    sync.logger.handlers = [handler]
    try:
        with patch.multiple(sync, **mocks), patch.object(sys, 'argv', ['sync', 'AUDIT', *args]), \
             patch.dict(os.environ, {'FEISHU_APP_ID': 'synthetic', 'FEISHU_APP_SECRET': 'synthetic'}), \
             contextlib.redirect_stdout(io.StringIO()):
            rc = sync.main()
    finally:
        sync.logger.handlers = old_handlers
    LAST_LOG[0] = log.getvalue()
    done = [line.split('Done: ', 1)[1] for line in log.getvalue().splitlines() if 'Done: ' in line]
    return rc, json.loads(done[-1]) if done else {}


# ── 11-26 补: FeishuClient 出错怎么报、重不重试 ──────────────────────────────────────────────────────────
APP, TBL = 'bascnSYNTHAPPTOKEN00000001', 'tblSYNTH0001'      # 一眼假的标识, 不是哪张真表的
JWT = 'eyJ' + 'a' * 30 + '.' + 'b' * 30 + '.' + 'c' * 30


class FakeResp:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body, dict(headers or {})
    def json(self):
        if self._body is None:
            raise ValueError('synthetic non-JSON body')
        return self._body
    def raise_for_status(self):              # _ensure_token 还在用
        if self.status_code >= 400:
            raise requests.HTTPError(f'{self.status_code} synthetic')


def _ok(n, more, pt=None):
    data = dict(items=[dict(record_id=f'p{n}r{i}', fields={'body': 'synthetic'}) for i in range(2)], has_more=more)
    if more:
        data['page_token'] = pt
    return FakeResp(200, dict(code=0, msg='success', data=data))


def _err(status, code, msg='synthetic', headers=None):
    return FakeResp(status, dict(code=code, msg=msg, error=dict(log_id='LOGID123')), headers)


def _pages(n_ok, *tail):
    """前 n_ok 页好的 (第 i 页回 page_token PTi), 后面接 tail。"""
    return [_ok(i, True, f'PT{i}') for i in range(1, n_ok + 1)] + list(tail)


class FakeFeishu:
    """requests.get / requests.post / time.sleep 换成按脚本回的假货。每次 GET 记下 params / headers (当场拷贝: params 会被原地改)。"""
    def __init__(self, script):
        self.script, self.calls, self.sleeps, self.posts = list(script), [], [], 0
    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append((url, dict(params or {}), dict(headers or {})))
        nxt = self.script.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt
    def post(self, url, json=None, timeout=None):
        self.posts += 1
        return FakeResp(200, dict(code=0, tenant_access_token='t-new', expire=7200))
    def big_sleeps(self):
        return [x for x in self.sleeps if x >= 1]        # 翻页之间那 0.1 秒不算
    def __enter__(self):
        self._patches = [patch.object(sync.requests, 'get', self.get), patch.object(sync.requests, 'post', self.post),
                         patch.object(sync.time, 'sleep', self.sleeps.append)]
        for p in self._patches:
            p.start()
        return self
    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


def _client():
    c = sync.FeishuClient('synthetic', 'synthetic')
    c._token, c._token_expires_at = 't-old', 10 ** 12
    return c


def _records():
    return list(_client().list_records(APP, TBL))


def _fails(script, call=_records):
    """跑到抛 FeishuAPIError 为止 → (异常, str, FakeFeishu)。整段 traceback 里不许有 URL / app_token / page_token,
    也不许挂着异常链 (requests 的异常文本里就是整条 URL)。"""
    with FakeFeishu(script) as h:
        try:
            call()
        except sync.FeishuAPIError as e:
            exc = e
        else:
            raise AssertionError('该抛 FeishuAPIError, 没抛')
    text = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    for bad in (APP, 'open.feishu.cn', 'page_token=', 'http', *({c[1].get('page_token') for c in h.calls} - {None})):
        assert bad not in text, f'报错里漏了 {bad!r}: {text[-400:]}'
    assert exc.__cause__ is None and exc.__suppress_context__, '异常链里会带着 requests 的原文 (URL)'
    return exc, str(exc), h


def check_feishu_client():
    # F0 反证: 老路子 (raise_for_status) 的报错文本里真有 app_token —— 下面那些「不许有」不是空跑
    resp = requests.Response()
    resp.status_code, resp.url = 400, f'https://open.feishu.cn/open-apis/bitable/v1/apps/{APP}/tables/{TBL}/records?page_token=PT4'
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        assert APP in str(e), 'F0'
    else:
        raise AssertionError('F0 raise_for_status 没抛')

    # F1 WTG 的样子: 前 4 页好的, 第 5 页 400 / 1254607 (Data not ready), 同一个 page_token 再试就好了 → 10 行, 不重行
    with FakeFeishu(_pages(4, _err(400, 1254607, 'Data not ready, please try again later'), _ok(5, False))) as h:
        items = _records()
    assert len(items) == 10 and len({i['record_id'] for i in items}) == 10, f'F1 第 5 页重试之后要接着读完、不重行: {len(items)}'
    assert [c[1].get('page_token') for c in h.calls[-2:]] == ['PT4', 'PT4'] and len(h.calls) == 6, 'F1 同一个 page_token 重试这一页'
    assert h.big_sleeps() == [3], f'F1 HTTP 400 的重试至少等 3 秒: {h.sleeps}'
    # F1b 没见过的 code 的 400 (或回包不是 JSON) 只再试一次, 第二次好了照常读完
    for bad in (_err(400, 1254999), FakeResp(400, None)):
        with FakeFeishu(_pages(4, bad, _ok(5, False))) as h:
            assert len(_records()) == 10 and len(h.calls) == 6 and h.big_sleeps() == [3], f'F1b 400 之后 200 要读完: {h.sleeps}'

    # F2 没见过的 400 连着两次 → 不再试第三次, 报错里有 状态码 / code / msg / 第几页 / 共试几次 / log_id
    exc, s, h = _fails(_pages(4, _err(400, 1254999), _err(400, 1254999)))
    for want in ('飞书 list_records 第 5 页失败', 'HTTP 400', 'code=1254999', 'msg=synthetic', '共试 2 次', 'log_id=LOGID123'):
        assert want in s, f'F2 报错里要有 {want}: {s}'
    assert len(h.calls) == 6 and h.big_sleeps() == [3] and (exc.status, exc.code, exc.page) == (400, 1254999, 5), (len(h.calls), h.sleeps)
    # F2b 文档说「等一会儿重试」的 code 一直不好 → 试满 3 次, 每次至少等 3 秒
    exc, s, h = _fails([_err(400, 1254607)] * 3)
    assert len(h.calls) == 3 and h.big_sleeps() == [3, 3] and '共试 3 次' in s, (len(h.calls), h.sleeps, s)

    # F3 重试也一样错的 code (id 不对 / 没权限 / 回包太大 / 参数校验) 和别的 4xx → 一次就报, 不等
    for status, code in ((400, 1254302), (400, 1254040), (200, 1254030), (400, 99991672), (403, 91402), (404, 1254999),
                         (200, 1254999)):
        exc, s, h = _fails([_err(status, code)])
        assert len(h.calls) == 1 and not h.big_sleeps() and f'HTTP {status}' in s and f'code={code}' in s, \
            f'F3 HTTP {status} / {code} 不该重试: {len(h.calls)} {s}'

    # F4 429: 按回包头 x-ogw-ratelimit-reset 等 (封顶 10 秒); 没有这个头就 1 / 2 秒; 试满 3 次报 HTTP 429
    with FakeFeishu([_err(429, 99991400, headers={'x-ogw-ratelimit-reset': '2'}), _ok(1, False)]) as h:
        assert len(_records()) == 2
    assert h.big_sleeps() == [2], f'F4 按 x-ogw-ratelimit-reset 等: {h.sleeps}'
    with FakeFeishu([_err(429, 99991400, headers={'x-ogw-ratelimit-reset': '999'}), _ok(1, False)]) as h:
        _records()
    assert h.big_sleeps() == [10], f'F4 等的秒数封顶 10: {h.sleeps}'
    exc, s, h = _fails([_err(429, 99991400)] * 3)
    assert len(h.calls) == 3 and 'HTTP 429' in s and 'code=99991400' in s and h.big_sleeps() == [1, 2], (len(h.calls), h.sleeps, s)
    # F5 老接口的频控回 HTTP 400 + 99991400 → 同样重试 (400 至少等 3 秒); F6 HTTP 200 + 1254290 TooManyRequest → 重试
    with FakeFeishu([_err(400, 99991400), _ok(1, False)]) as h:
        _records()
    assert len(h.calls) == 2 and h.big_sleeps() == [3], f'F5: {h.sleeps}'
    with FakeFeishu([_err(200, 1254290), _ok(1, False)]) as h:
        _records()
    assert len(h.calls) == 2 and h.big_sleeps() == [1], f'F6: {h.sleeps}'

    # F7 5xx 照旧退避 1 / 2 秒、最多 3 次; 试满了报 FeishuAPIError (不是 requests.HTTPError), 回包不是 JSON 也说得清
    with FakeFeishu([FakeResp(503), FakeResp(503), _ok(1, False)]) as h:
        assert len(_records()) == 2
    assert h.big_sleeps() == [1, 2], f'F7: {h.sleeps}'
    exc, s, h = _fails([FakeResp(503)] * 3)
    assert 'HTTP 503' in s and '非 JSON' in s and len(h.calls) == 3, s

    # F8 401 或 token 失效的 code → 刷一次 token (不占次数), 原地改 headers, 后面几页也用新 token; 刷过还 401 → 报, 不死循环
    for first in (FakeResp(401, dict(code=99991663, msg='synthetic')), _err(400, 99991663)):
        with FakeFeishu([first, _ok(1, True, 'PT1'), _ok(2, False)]) as h:
            assert len(_records()) == 4
        assert h.posts == 1 and [c[2]['Authorization'] for c in h.calls] == ['Bearer t-old', 'Bearer t-new', 'Bearer t-new'], \
            f'F8 刷一次 token、后面几页跟着用: {h.posts} {[c[2] for c in h.calls]}'
    exc, s, h = _fails([FakeResp(401, dict(code=99991663, msg='synthetic'))] * 2)
    assert h.posts == 1 and len(h.calls) == 2 and 'HTTP 401' in s, (h.posts, len(h.calls), s)

    # F9 断线: requests 的异常文本里是整条 URL (带 app_token) → 只留类名
    leak = requests.ConnectionError(f'Max retries exceeded with url: /open-apis/bitable/v1/apps/{APP}/tables/{TBL}/records?page_size=100')
    exc, s, h = _fails([leak, leak, leak])
    assert 'ConnectionError' in s and h.big_sleeps() == [1, 2] and '共试 3 次' in s, (h.sleeps, s)

    # F10 飞书回的 msg 里带着 app_token / page_token / 密钥 → 掩掉, 截到 200 字; F10b 先掩再截 (先截会漏半截 JWT)
    exc, s, h = _fails(_pages(1, _err(400, 1254003, f'app_token {APP} wrong {JWT} page PT1 ' + 'z' * 500)))
    assert '***REDACTED***' in s and '<redacted>' in s and len(exc.msg) <= 200, (len(exc.msg), s)
    exc, s, h = _fails([_err(400, 1254003, 'z' * 150 + JWT)])
    assert 'eyJ' not in s, f'F10b 先截再掩: {s}'
    # F11 回包不是 JSON 的 400 连着两次 → 报「非 JSON」, 原文不往外回
    exc, s, h = _fails([FakeResp(400), FakeResp(400)])
    assert '非 JSON' in s and len(h.calls) == 2, s
    # F11b 读表结构 (风控来源列闸) 走同一套
    fields_ok = FakeResp(200, dict(code=0, msg='success', data=dict(items=[dict(field_name='body'), dict(field_name='x')], has_more=False)))
    with FakeFeishu([_err(400, 1254999), fields_ok]) as h:
        assert _client().list_field_names(APP, TBL) == {'body', 'x'} and len(h.calls) == 2
    exc, s, h = _fails([_err(400, 1254999)] * 2, lambda: _client().list_field_names(APP, TBL))
    assert '飞书 list_fields 第 1 页失败' in s and 'code=1254999' in s, s

    # F12 真的 main(), 不打码的 StreamHandler: 第 2 页 400 连着两次 → 这一步红、不算完整同步、第 1 页照写;
    #     日志里有 状态码 / code, 没有 app_token 和 URL。换成「等一会儿重试」的 code、第二次好了 → 绿、完整同步。
    db = Database()
    with FakeFeishu(_pages(1, _err(400, 1254999), _err(400, 1254999))):
        rc, stats = run(db, [], feishu=sync.FeishuClient, app_token=APP)
    log = LAST_LOG[0]
    assert rc == 1 and stats['errors'] == 1 and stats['scan_completed'] == 0 and stats['upserted'] == 2, (rc, stats)
    for want in ('飞书表抓取失败', 'HTTP 400', 'code=1254999', '第 2 页'):
        assert want in log, f'F12 日志里要有 {want}: {log[-600:]}'
    assert APP not in log and 'open.feishu.cn' not in log, f'F12 日志里漏了 app_token / URL: {log[-600:]}'
    assert 'Traceback' not in log, f'F12 FeishuAPIError 的文本已经说清了, 不再带 traceback: {log[-600:]}'
    db = Database()
    with FakeFeishu(_pages(1, _err(400, 1254607), _ok(2, False))):
        rc, stats = run(db, [], feishu=sync.FeishuClient, app_token=APP)
    assert rc == 0 and stats['errors'] == 0 and stats['upserted'] == 4 and stats['scan_completed'] == 1, (rc, stats)

    # F13 (11-26 复审补) 回包 code=0 可形状不对 → 报 (HTTP 200 · code=0), 不当空页: 没有 data / data 是 null /
    #     说有下一页却没有 items 或 page_token / items 不是列表。老代码在前两种上是抛的 (data["data"]), 当空页放过去这一晚就
    #     「扫完了」, 这张表的帖全被对账报成消失。
    for body in (dict(code=0, msg='success'), dict(code=0, msg='success', data=None),
                 dict(code=0, msg='success', data=dict(items=None, has_more=True, page_token='PT1')),
                 dict(code=0, msg='success', data=dict(items=[], has_more=True)),
                 dict(code=0, msg='success', data=dict(items='x', has_more=False))):
        exc, s, h = _fails([FakeResp(200, body)])
        assert len(h.calls) == 1 and 'HTTP 200' in s and 'code=0' in s and '共试' not in s, f'F13 {body}: {s}'
    # 空表的最后一页 (items 是 null / 没有、has_more 假) 照旧是空页
    for data in (dict(items=None, has_more=False), dict(has_more=False), {}):
        with FakeFeishu([FakeResp(200, dict(code=0, msg='success', data=data))]):
            assert _records() == [], f'F13 空表 {data}'
    exc, s, h = _fails([FakeResp(200, dict(code=0, msg='success'))], lambda: _client().list_field_names(APP, TBL))
    assert '飞书 list_fields 第 1 页失败' in s and '回包没有 data' in s, s
    # 走真的 main(): 库里有 a、b, 这一晚回包没有 data → 红、不算扫完、不对账 (a、b 不报消失)
    db = Database()
    assert run(db, ['a', 'b'])[0] == 0
    with FakeFeishu([FakeResp(200, dict(code=0, msg='success'))]):
        rc, stats = run(db, [], feishu=sync.FeishuClient, app_token=APP)
    assert rc == 1 and stats['errors'] == 1 and stats['scan_completed'] == 0 and not db.vanished(), (rc, stats, db.vanished())
    assert '回包没有 data' in LAST_LOG[0], LAST_LOG[0][-600:]

    # F14 (11-26 复审补) 上面没钉到的几处:
    # a) 读超时 (ReadTimeout 不是 ConnectionError) 一样退避重试; 试满只留类名 (它的异常文本里也是整条 URL)
    tmo = requests.ReadTimeout(f"HTTPSConnectionPool(host='open.feishu.cn'): Read timed out. "
                               f"url: /open-apis/bitable/v1/apps/{APP}/tables/{TBL}/records?page_size=100")
    with FakeFeishu([tmo, _ok(1, False)]) as h:
        assert len(_records()) == 2
    assert len(h.calls) == 2 and h.big_sleeps() == [1], f'F14a 读超时要重试: {h.sleeps}'
    exc, s, h = _fails([tmo] * 3)
    assert 'ReadTimeout' in s and h.big_sleeps() == [1, 2] and '共试 3 次' in s, (h.sleeps, s)
    # b) 刷 token 不占次数: 503、401、503、好 → 4 次 GET、换 1 次 token、等 1 / 2 秒, 读完
    with FakeFeishu([FakeResp(503), FakeResp(401, dict(code=99991663, msg='synthetic')), FakeResp(503), _ok(1, False)]) as h:
        assert len(_records()) == 2
    assert len(h.calls) == 4 and h.posts == 1 and h.big_sleeps() == [1, 2], f'F14b: {len(h.calls)} {h.posts} {h.sleeps}'
    # c) 飞书 msg 里带着 view_id → 掩掉
    exc, s, h = _fails([_err(400, 1254003, 'view vewSYNTH0001 not found')],
                       lambda: list(_client().list_records(APP, TBL, view_id='vewSYNTH0001')))
    assert '<redacted>' in s and 'vewSYNTH0001' not in s, f'F14c: {s}'
    # d) 回包里的 log_id 不像个 id (带空格 / 换行 / 太长) → 不往日志里写
    for lid in ('LOG ID', 'LOGID\nforged line', 'x' * 65):
        exc, s, h = _fails([FakeResp(400, dict(code=1254003, msg='synthetic', error=dict(log_id=lid)))])
        assert 'log_id=' not in s and exc.log_id is None, f'F14d {lid!r}: {s}'
    # e) HTTP 5xx 的回包里 code 是 0 也不算成功: 照 5xx 重试、试满报
    exc, s, h = _fails([FakeResp(503, dict(code=0, msg='success', data=dict(items=[], has_more=False)))] * 3)
    assert len(h.calls) == 3 and 'HTTP 503' in s and 'code=0' in s, f'F14e: {s}'

    # 源码: 拿到回包不再交给 requests 的状态检查 (它的报错文本就是整条 URL)
    for fn in (sync.FeishuClient.list_records, sync.FeishuClient.list_field_names, sync.FeishuClient._get_with_retry):
        assert '.raise_for_status(' not in inspect.getsource(fn), f'{fn.__name__} 又用回了 raise_for_status()'
    print('  Feishu client: 400 同一页只再试一次 · 1254607 / 5xx 退避 · 429 按回包头等 · 401 刷一次 token · '
          '重试也一样错的 code 立刻报 · 报错带 code / msg、不带 URL / app_token / view_id · 读超时也重试 · 刷 token 不占次数 · '
          'code=0 可回包没有 data 也报、不当空页 (F0-F14) ✓')


def check_source_guards():
    """The parts of the removed COR-011 CI block that the behavioural test above cannot see."""
    src = inspect.getsource(sync.main)
    # One criterion, computed once, shared by stamping and reconciliation.
    assert src.count("full_scan = ") == 1, "full_scan 被算了不止一次"
    assert "full_scan = (not truncated_by_limit) and (not fetch_failed)" in src and "records_all_ok" in src
    assert "writes_all_ok = len(written_ids) == len(pending_notes)\n" in src, \
        "对账 / 账本只看 note 写全没有; 指标和账号的失败不许挡 (D-153)"
    # Report-only: notes has six ON DELETE CASCADE children and rows already pushed to another database.
    recon = src[src.index("对账: 这次完整扫描没见到的"):]
    for forbidden in (".delete(", '"is_deleted"', '"deleted_at"', "tombstone", '.update({"tier"'):
        assert forbidden not in recon, f"对账里出现了 {forbidden!r} —— 这次刻意只报不删"
    # Downstream impact is reported with the vanished list, lesson cards included (CASCADE on note).
    for col in ("synced_to_ssll_at", "synced_to_aw_at", "essence_annotated_at", "flywheel_lesson_annotations"):
        assert col in recon, f"对账没报 {col} —— 清理时不知道要先撤什么"
    # Pre-v1.25 path kept whole: NULL counts as "not this run", concurrent stamps excluded, never-seen apart.
    for needle in ("last_seen_run_id.is.null", "last_seen_run_id.neq.", 'last_seen_at"] >= run_started_at',
                   "missing = [r for r in missing", 'not r.get("last_seen_run_id")'):
        assert needle in recon, f"账本没建时的老对账缺了: {needle}"
    stamp = src[src.index("if full_scan:"):]
    assert "_iso_now_tz()" in stamp, "last_seen_at(TIMESTAMPTZ)用了 naive 的 _iso_now()"
    # Deployment contract: every column / object the sync writes has a migration in the first-deploy list.
    readme = (pathlib.Path(__file__).resolve().parent / "README.md").read_text(encoding="utf-8")
    step0 = readme[readme.index("第一次部署"):readme.index("Step 1")]
    for col in ("last_seen_at", "last_seen_run_id"):
        assert col in src, f"脚本不再写 {col}? 那这条断言该改了"
    for name in ("notes_v1_9", "notes_v1_25_sync_runs.sql", "notes_v1_26_feature_failure_recovery.sql"):
        assert name in step0, f"{name} 不在 scripts/README.md 的首次部署清单里"
    # The ledger is optional until the owner runs v1.25: it must never be a hard schema requirement again.
    for table in ("note_sync_runs", "note_sync_presence"):
        assert table not in _required_columns(), f"{table} 进了 _REQUIRED_COLUMNS —— 没跑迁移的库上整条同步会被挡 (owner 11-02)"


def _required_columns():
    import _common
    return _common._REQUIRED_COLUMNS


def main():
    db = Database()
    assert run(db, ['a', 'b'])[0] == 0 and db.completed() == 1
    rc, stats = run(db, [])
    assert rc == 0 and stats['scan_completed'] == 1 and stats['reconcile_vanished'] == 2
    assert db.vanished() == {'AUDIT_a', 'AUDIT_b'}, 'empty successful scan must advance'

    db = Database()
    assert run(db, ['a', 'b'])[0] == 0
    db.fail_writes = {'AUDIT_b'}
    assert run(db, ['a', 'b'])[0] == 1 and db.completed() == 1
    assert not db.vanished(), 'partial note write must not publish a false deletion'
    db.fail_writes.clear()
    assert run(db, ['a', 'b'], '--limit', '10')[0] == 0 and db.completed() == 1
    assert run(db, ['a'], fetch_fail=True)[0] == 1 and db.completed() == 1
    assert run(db, ['a'], '--dry-run')[0] == 0 and db.completed() == 1
    db.fail_complete = True
    assert run(db, ['a'])[0] == 1 and db.completed() == 1
    db.fail_complete = False
    assert run(db, ['a'])[0] == 0 and db.vanished() == {'AUDIT_b'}
    # Every Done line carries scan_completed, also when nothing was completed (T7).
    for extra in (['--limit', '10'], ['--dry-run']):
        assert run(db, ['a'], *extra)[1]['scan_completed'] == 0

    # ── v1.25 not applied yet (owner rule 11-02): ingest exactly as before, warn once, scan_completed=0 ──
    import _common
    _common._MISSING_DB_OBJECT_WARNED.discard('notes_v1_25')
    db.fail_begin = 'missing'
    completed_before, presence_before = db.completed(), dict(db.presence)
    warnings = 0
    for ids in (['a', 'c'], ['a', 'c', 'd']):
        rc, stats = run(db, ids)
        assert rc == 0 and stats['scan_completed'] == 0, (rc, stats)
        assert stats['upserted'] == len(ids) and 'AUDIT_c' in db.notes, 'notes must still be ingested without the migration'
        assert db.notes['AUDIT_c'].get('last_seen_run_id'), 'the pre-v1.25 path still stamps a full scan'
        # the old stamp-based reconciliation ran: vanished vs never-seen kept apart, as on origin/main
        assert stats['reconcile_vanished'] == 1 and stats['reconcile_never_seen'] == 1, stats
        warnings += LAST_LOG[0].count(sync.LEDGER_MIGRATION)
    assert db.legacy_reads == 2 and warnings == 1, (db.legacy_reads, warnings)
    assert db.completed() == completed_before and db.presence == presence_before, 'no ledger write without the ledger'
    # ── a transient begin error is not "apply the migration": red, notes still ingested, no reconciliation ──
    db.fail_begin = 'transient'
    reads = db.legacy_reads
    rc, stats = run(db, ['a', 'e'])
    assert rc == 1 and stats['scan_completed'] == 0 and stats['errors'] == 1 and 'AUDIT_e' in db.notes, (rc, stats)
    assert sync.LEDGER_MIGRATION not in LAST_LOG[0] and 'connection reset' in LAST_LOG[0]
    assert db.legacy_reads == reads and 'reconcile_vanished' not in stats
    db.fail_begin = False

    # ── metric / account write failures: red, counted, but the scan still completes (T7) ──
    db = Database()
    assert run(db, ['a', 'b'])[0] == 0
    rc, stats = run(db, ['a'], metrics=(0, ['AUDIT_a']), accounts=['acct'])
    assert rc == 1 and stats['metrics_failed'] == 1 and stats['accounts_failed'] == 1, stats
    assert stats['scan_completed'] == 1 and db.vanished() == {'AUDIT_b'}, 'membership evidence needs the notes only'
    assert '指标 1 条 / 账号 1 个没写成' in LAST_LOG[0]
    # D-058 probe saw no existing failed note. An older concurrent scan may
    # create it before or after this run completes; both orderings retain the
    # newer observation rather than incorrectly declaring it absent.
    class InterleavingDatabase(Database):
        inject_before = False
        def write(self, _, notes, **kwargs):
            if self.inject_before:
                self.inject_before = False
                self.notes['AUDIT_bad'] = dict(note_id='AUDIT_bad', project_id='AUDIT')
                self.rpc('complete_note_sync', dict(p_run_id='older', p_note_ids=['AUDIT_a','AUDIT_bad'])).execute()
            return super().write(_, notes, **kwargs)
    for earlier_insert in (True, False):
        db = InterleavingDatabase()
        assert run(db, ['a'])[0] == 0
        db.runs['older'] = dict(seq=2, completed=False)
        db.inject_before = earlier_insert
        rc, stats = run(db, ['a','bad'], fail_records={'bad'})
        assert rc == 1 and stats['scan_completed'] == 1
        if not earlier_insert:
            assert 'AUDIT_bad' not in db.notes and 'AUDIT_bad' in db.presence
            db.notes['AUDIT_bad'] = dict(note_id='AUDIT_bad',project_id='AUDIT')
            db.rpc('complete_note_sync',dict(p_run_id='older',p_note_ids=['AUDIT_a','AUDIT_bad'])).execute()
        assert 'AUDIT_bad' not in db.vanished(), 'a row observed by newer scan became falsely absent'
    check_feishu_client()
    check_source_guards()
    print('completed scan main: empty / partial / limit / later page / dry-run / rollback / recovery / '
          'missing migration = old path + one warning / transient begin error / metric failure / '
          'Feishu client (400 once / 429 / 5xx / 401 / never-retry codes / no URL or app_token in errors / '
          'malformed code-0 page is an error, F0-F14) / '
          'COR-011 source guards passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
