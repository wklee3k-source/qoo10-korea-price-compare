"""현황 리포트 HTML을 데이터만 받아 새로 찍어낸다.

[왜 만들었나 — 실측 2026-08-16]
그동안은 직전 회차 HTML을 문자열 치환으로 고쳐 썼다. 회차가 쌓이면서
태그가 어긋나기 시작했고(table 열림 5 / 닫힘 6, div 48 / 50), 결국
화면이 통째로 무너졌다. 표가 문단으로 흘러내리고 지난 회차 표가
지워지지 않은 채 남았다.

원인은 방식 자체다. 치환은 "그 문자열이 거기 그대로 있다"는 전제에
기대는데, 회차마다 값이 바뀌므로 그 전제가 무너진다. 하나라도 빗나가면
조용히 실패하고, 실패가 누적되면 구조가 깨진다.

이제 매번 처음부터 찍는다. 데이터가 바뀌어도 구조는 항상 같다.
"""

from __future__ import annotations

import html
from pathlib import Path

CSS = """
  :root{
    --bg:#0f1115; --card:#171a21; --card2:#1e222b; --border:#2a2e38;
    --text:#e6e8ec; --sub:#9aa1ad;
    --ok:#3ecf8e; --warn:#f5c344; --bad:#f26d6d; --info:#5fa8f5; --pp:#a78bfa;
  }
  *{box-sizing:border-box;}
  body{margin:0; padding:18px 14px 40px; background:var(--bg); color:var(--text);
    font-family:"Pretendard","Apple SD Gothic Neo","Malgun Gothic",sans-serif; line-height:1.55;}
  .wrap{max-width:1000px; margin:0 auto;}
  h1{font-size:19px; margin:0 0 2px;}
  .meta{color:var(--sub); font-size:12px; margin-bottom:14px;}
  h2{font-size:13.5px; margin:20px 0 7px; padding-bottom:5px; border-bottom:1px solid var(--border);}
  h2 .num{color:var(--info); font-weight:700;}
  .card{background:var(--card); border:1px solid var(--border); border-radius:9px;
    padding:11px 13px; margin-bottom:7px;}
  .badge{display:inline-block; font-size:11px; font-weight:700; padding:3px 9px;
    border-radius:999px; white-space:nowrap;}
  .badge.ok{background:rgba(62,207,142,.15); color:var(--ok);}
  .badge.warn{background:rgba(245,195,68,.15); color:var(--warn);}
  .badge.bad{background:rgba(242,109,109,.15); color:var(--bad);}
  table{width:100%; border-collapse:collapse; font-size:12.5px;}
  th{text-align:left; color:var(--sub); font-weight:600; padding:5px 7px;
    border-bottom:1px solid var(--border); white-space:nowrap;}
  td{padding:5px 7px; border-bottom:1px solid rgba(42,46,56,.5);}
  td.num{text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap;}
  .delta.up{color:var(--ok);} .delta.down{color:var(--bad);} .delta.zero{color:var(--sub);}
  .src{color:var(--sub); font-size:11px; margin-top:8px; line-height:1.6;}

  /* 신호등 */
  .signals{display:flex; gap:12px; flex-wrap:wrap; margin-bottom:16px;}
  .signal{flex:1 1 300px; display:flex; align-items:center; gap:14px;
    border-radius:14px; padding:16px 18px; border:2px solid;}
  .signal.green{background:linear-gradient(135deg,#0f2418,#161b22); border-color:#1f6b4d;}
  .signal.amber{background:linear-gradient(135deg,#241a0f,#191b20); border-color:#8a5a1e;}
  .signal.red{background:linear-gradient(135deg,#2a1214,#191b20); border-color:#7a2424;}
  .signal .dot{flex:0 0 46px; height:46px; border-radius:50%; display:flex;
    align-items:center; justify-content:center; font-size:22px; font-weight:800;}
  .signal.green .dot{background:rgba(62,207,142,.16); color:var(--ok);}
  .signal.amber .dot{background:rgba(245,195,68,.16); color:var(--warn);}
  .signal.red .dot{background:rgba(242,109,109,.16); color:var(--bad);}
  .signal .txt .lb{font-size:11px; color:var(--sub); letter-spacing:.03em;}
  .signal .txt h3{margin:1px 0 3px; font-size:16px;}
  .signal .txt p{margin:0; font-size:12px; color:var(--sub);}

  /* 할 일 카드 */
  .todo{background:var(--card); border:1px solid var(--border); border-left:3px solid var(--warn);
    border-radius:10px; padding:15px 17px; margin-bottom:10px;}
  .todo.done{border-left-color:var(--ok);}
  .todo .ttl{font-size:14.5px; font-weight:700; margin-bottom:8px;}
  .todo .how{font-size:12px; color:var(--sub); margin-bottom:10px;}
  .todo .prog{display:flex; align-items:center; gap:10px;}
  .todo .bar{flex:1; height:7px; background:var(--card2); border-radius:99px; overflow:hidden;}
  .todo .bar i{display:block; height:100%; background:var(--info);}
  .todo .pct{font-size:11.5px; color:var(--sub); white-space:nowrap;}

  /* 워커 카드 */
  .units{display:flex; gap:10px; flex-wrap:wrap;}
  .u{flex:1 1 220px; background:var(--card); border:1px solid var(--border);
    border-radius:10px; padding:13px 15px;}
  .u.warn{border-color:#8a5a1e;}
  .u.bad{border-color:#7a2424;}
  .u .nm{display:flex; justify-content:space-between; align-items:baseline; margin-bottom:7px;}
  .u .nm span:first-child{font-size:13.5px; font-weight:700;}
  .u .nm span:last-child{font-size:11px; color:var(--sub);}
  .u .st{font-size:11.5px; color:var(--sub); margin-bottom:9px;}
  .u .lamps{display:flex; gap:5px; flex-wrap:wrap;}
  .lamp{display:flex; align-items:center; gap:4px; background:var(--card2);
    border-radius:6px; padding:3px 7px; font-size:10.5px; color:var(--sub);}
  .lamp i{width:6px; height:6px; border-radius:50%; display:block;}
  .lamp.ok i{background:var(--ok);}
  .lamp.warn i{background:var(--warn);}
  .lamp.bad i{background:var(--bad);}
  .lamp .no{font-weight:700; color:var(--text);}

  /* 파이프라인 중첩 박스 */
  .nest{background:var(--card); border:1px solid var(--border); border-radius:10px; padding:14px;}
  .lv{border-radius:8px; padding:10px 12px; margin-top:8px;}
  .lv:first-child{margin-top:0;}
  .lv .hd{font-size:12.5px; font-weight:700; margin-bottom:7px;}
  .lv .hd .v{color:var(--info); font-variant-numeric:tabular-nums;}
  .lv .hd .dd{color:var(--sub); font-weight:400; font-size:11px;}
  .leafs{display:flex; gap:4px; flex-wrap:wrap;}
  .leaf{display:flex; align-items:baseline; gap:5px; background:rgba(0,0,0,.22);
    border-radius:6px; padding:5px 9px; font-size:11px;}
  .leaf .t{color:var(--sub);}
  .leaf .v{font-weight:700; font-variant-numeric:tabular-nums;}
  .leaf .p{color:var(--sub); font-size:9.5px;}
  /* ── 중첩 박스: 안으로 들어갈수록 밝아진다 ─────────────
     [실패했던 방식 — 2026-08-17] 층마다 다른 색(파랑/보라/초록)을
     주고 여백을 7px로 좁혔더니, 색이 서로 대등해 보여 "나란한 것"으로
     읽혔다. 사장님이 "상하 관계가 명확히 보이지 않는다"고 지적.

     고친 방향: **색으로 층을 나누지 않는다.** 같은 색 계열에서
     안으로 갈수록 배경을 밝게 하고, 부모 여백을 넉넉히 줘서
     자식 둘레에 부모 색이 보이게 한다. 그러면 "안에 들어있다"가
     눈으로 읽힌다. 색은 결과(초록/노랑/파랑/회색)에만 쓴다. */
  .lv{border-radius:8px; overflow:hidden; margin-top:7px;}
  .lv:first-child{margin-top:0;}
  .lv > .hd{margin:0; padding:8px 12px; font-size:12.5px; font-weight:700;
    display:flex; align-items:center; gap:8px;}
  .lv > .hd .v{font-size:15px; font-weight:800;}
  .lv > .hd .dd{font-size:10.5px; font-weight:500; opacity:.75;}
  .lv > .leafs{padding:8px 12px 10px;}
  /* 자식 박스는 부모 안쪽으로 들여쓴다 — 좌우 12px, 아래 10px */
  .lv > .lv{margin:0 12px 10px;}

  /* 깊이별 배경: 바깥이 어둡고 안이 밝다 */
  .d1{background:#1b1f28; border:1px solid #3a4152;}
  .d1 > .hd{background:#2b3242; color:#cfd6e4;}
  .d2{background:#232936;} .d2 > .hd{background:#333c4e; color:#dce3f0;}
  .d3{background:#2b3241;} .d3 > .hd{background:#3d475b; color:#e6ebf5;}
  .d4{background:#333b4c;} .d4 > .hd{background:#4a5568; color:#eff3fa;}
  .d5{background:#3c4557;} .d5 > .hd{background:#586274; color:#fff;}
  .d6{background:#464f63;} .d6 > .hd{background:#66718a; color:#fff;}
  .lv > .hd .v{color:#fff;}

  /* 단계 번호에 색 점을 찍어 어느 단계인지 표시 */
  .step{display:inline-block; width:9px; height:9px; border-radius:50%;
    flex:0 0 9px;}
  .s1{background:#5fa8f5;} .s2{background:#a78bfa;} .s3{background:#3ecf8e;}
  .s4{background:#f5c344;} .s5{background:#f48c50;}

  /* 잎사귀 — 결과에 따라 색이 다르다 */
  .leaf{border:none; padding:5px 9px; font-size:10.5px; border-radius:5px;
    gap:5px;}
  .leaf .v{font-size:12px; font-weight:800;}
  .leaf.go{background:#1f8f5f;} .leaf.go .t{color:#d6fbe9;}
  .leaf.go .v{color:#fff;} .leaf.go .p{color:#bff0da;}
  .leaf.todo{background:#b8860b;} .leaf.todo .t{color:#fff4d6;}
  .leaf.todo .v{color:#fff;} .leaf.todo .p{color:#ffeab8;}
  .leaf.wait{background:#2b6cb0;} .leaf.wait .t{color:#dceafd;}
  .leaf.wait .v{color:#fff;} .leaf.wait .p{color:#c3dcfa;}
  .leaf.drop{background:#454b58;} .leaf.drop .t{color:#a3aab6;}
  .leaf.drop .v{color:#ccd2dc;} .leaf.drop .p{color:#939aa6;}
  .leaf:not(.go):not(.todo):not(.wait):not(.drop){background:#4a5262;}

  .nest{background:var(--card); border:1px solid var(--border);
    border-radius:9px; padding:9px;}

  /* ── 트리: 상하관계를 선으로 그린다 ──────────────────────
     [왜 — 사장님 지적 2026-08-17] 중첩 박스를 색으로 구분했더니
     오히려 "나란한 것"처럼 읽혔다. 층이 다른데 색만 다를 뿐
     들여쓰기가 얕아 부모-자식이 안 보인 것이다.
     세로선과 가로선을 실제로 그려 관계를 눈에 박는다. */
  .tree{background:var(--card); border:1px solid var(--border);
    border-radius:9px; padding:12px 14px;}
  .tree ul{list-style:none; margin:0; padding:0;}
  /* 자식 목록: 왼쪽에 세로 줄기를 두고 그만큼 들여쓴다 */
  .tree li > ul{margin-left:13px; padding-left:16px; border-left:2px solid #4a5262;}
  .tree li{position:relative; padding:3px 0;}
  /* 각 자식 앞 가로선 */
  .tree li > ul > li::before{content:""; position:absolute; left:-16px; top:15px;
    width:14px; height:2px; background:#4a5262;}
  /* 마지막 자식 아래로 줄기가 삐져나오지 않게 덮는다 */
  .tree li > ul > li:last-child::after{content:""; position:absolute; left:-18px;
    top:17px; bottom:-4px; width:3px; background:var(--card);}

  .node{display:inline-flex; align-items:center; gap:7px; border-radius:6px;
    padding:5px 11px; font-size:12px; font-weight:700; white-space:nowrap;}
  .node .v{font-size:14px; font-weight:800;}
  .node .dd{font-size:10.5px; font-weight:500; opacity:.85;}
  .node.n1{background:#2b6cb0; color:#fff;}
  .node.n2{background:#6b46c1; color:#fff;}
  .node.n3{background:#1f8f5f; color:#fff;}
  .node.n4{background:#b8860b; color:#fff;}
  .node.n5{background:#c05621; color:#fff;}
  .node.mid{background:#39404e; color:#e6e8ec;}
  .node.go{background:#1f8f5f; color:#fff;}
  .node.todo{background:#b8860b; color:#fff;}
  .node.wait{background:#2b6cb0; color:#fff;}
  .node.drop{background:#3a3f4a; color:#aab1bd;}
  .node .arrow{font-size:10.5px; opacity:.9; font-weight:600;}

  .footer{margin-top:34px; padding-top:14px; border-top:1px solid var(--border);
    color:var(--sub); font-size:11px;}
"""


def esc(x) -> str:
    return html.escape(str(x), quote=False)


def num(x) -> str:
    return f"{x:,}" if isinstance(x, (int, float)) else esc(x)


def signal(kind: str, label: str, title: str, desc: str, mark: str) -> str:
    return (f'<div class="signal {kind}"><div class="dot">{esc(mark)}</div>'
            f'<div class="txt"><div class="lb">{esc(label)}</div>'
            f'<h3>{esc(title)}</h3><p>{esc(desc)}</p></div></div>')


def todo(title: str, how: str, done_n, total_n, finished=False) -> str:
    pct = (done_n / total_n * 100) if total_n else 100
    cls = "todo done" if finished else "todo"
    return (f'<div class="{cls}"><div class="ttl">{title}</div>'
            f'<div class="how">{esc(how)}</div>'
            f'<div class="prog"><div class="bar"><i style="width:{pct:.1f}%"></i></div>'
            f'<div class="pct">한것 {num(done_n)} / 전체 {num(total_n)} · {pct:.1f}%</div>'
            f'</div></div>')


def unit(name: str, count: str, state: str, lamps: list, tone: str = "") -> str:
    ls = "".join(f'<span class="lamp {t}"><i></i><span class="no">{esc(n)}</span>'
                 f'<span class="tm">{esc(v)}</span></span>' for n, v, t in lamps)
    cls = f"u {tone}".strip()
    return (f'<div class="{cls}"><div class="nm"><span>{esc(name)}</span>'
            f'<span>{esc(count)}</span></div>'
            f'<div class="st">{state}</div><div class="lamps">{ls}</div></div>')


def leaf(t: str, v, p: str = "", tone: str = "") -> str:
    """중첩 박스 안의 잎사귀.

    tone으로 색을 준다(사장님 요청 2026-08-17):
      go   초록 — 다음 단계로 넘어가는 것 (검수페이지 등)
      todo 노랑 — 사람이 손대야 하는 것 (보완·번역)
      wait 파랑 — 아직 처리 전인 것 (남은 분량)
      drop 회색 — 버려지는 것 (판매중지·합의부족)
    """
    ex = f'<span class="p">{esc(p)}</span>' if p else ""
    cls = f"leaf {tone}".strip()
    return (f'<span class="{cls}"><span class="t">{esc(t)}</span>'
            f'<span class="v">{num(v)}</span>{ex}</span>')


def sub(head: str, leafs: list, inner: str = "", tone: str = "") -> str:
    """중첩 박스 안의 한 단계 더 얕은 층.

    [왜 필요한가 — 사장님 지적 2026-08-17]
    검증 결과를 `구매링크 920 / 링크없음 1,420 / 합의부족 2,406 /
    남음 1,475`처럼 한 줄에 늘어놓았더니 관계가 안 보였다. 실제로는
    3층이고, 중간 단계인 `이름확정 2,340`이 아예 빠져 있었다.

        검증대상 6,221
        ├─ 완료 4,746
        │  ├─ 이름확정 2,340
        │  │  ├─ 구매링크 920
        │  │  └─ 링크없음 1,420
        │  └─ 합의부족 2,406
        └─ 남음 1,475

    **합이 맞는지 반드시 확인하고 리포트에 적는다.** 형제끼리 더하면
    부모가 나와야 한다. 안 맞으면 어딘가 빠뜨린 것이다.
    """
    body = f'<div class="leafs">{"".join(leafs)}</div>' if leafs else ""
    return (f'<div class="lv sub {tone}"><div class="hd">{head}</div>{body}{inner}</div>'
            if tone else
            f'<div class="lv sub"><div class="hd">{head}</div>{body}{inner}</div>')


def level(cls: str, head: str, leafs: list, inner: str = "") -> str:
    body = f'<div class="leafs">{"".join(leafs)}</div>' if leafs else ""
    return f'<div class="lv {cls}"><div class="hd">{head}</div>{body}{inner}</div>'


def table(headers: list, rows: list, note: str = "") -> str:
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    trs = []
    for r in rows:
        tds = []
        for c in r:
            if isinstance(c, tuple):
                val, cls = c
                tds.append(f'<td class="{cls}">{val}</td>')
            else:
                tds.append(f"<td>{c}</td>")
        trs.append("<tr>" + "".join(tds) + "</tr>")
    nt = f'<div class="src">{note}</div>' if note else ""
    return (f'<div class="card"><table><tr>{th}</tr>'
            + "".join(trs) + f"</table>{nt}</div>")



def node(label: str, value=None, tone: str = "mid", note: str = "",
         arrow: str = "") -> str:
    """트리의 한 마디.

    tone: n1~n5(단계 색) / mid(중간 단계) / go·todo·wait·drop(결과 색)
    """
    v = f'<span class="v">{num(value)}</span>' if value is not None else ""
    nt = f'<span class="dd">{esc(note)}</span>' if note else ""
    ar = f'<span class="arrow">{esc(arrow)}</span>' if arrow else ""
    return f'<span class="node {tone}">{esc(label)}{v}{nt}{ar}</span>'


def branch(head: str, children: list = None) -> str:
    """트리 가지. children이 있으면 자식 목록을 안에 넣는다."""
    kids = ("<ul>" + "".join(f"<li>{c}</li>" for c in children) + "</ul>"
            if children else "")
    return head + kids


def tree(root: str) -> str:
    return f'<div class="tree"><ul><li>{root}</li></ul></div>'



def box(depth: int, step: str, head: str, value=None, note: str = "",
        leafs: list = None, inner: str = "") -> str:
    """중첩 박스 한 겹.

    depth: 1~5 — 안으로 갈수록 배경이 밝아진다
    step:  s1~s5 또는 "" — 단계를 나타내는 색 점
    """
    dot = f'<span class="step {step}"></span>' if step else ""
    v = f'<span class="v">{num(value)}</span>' if value is not None else ""
    nt = f'<span class="dd">{esc(note)}</span>' if note else ""
    body = f'<div class="leafs">{"".join(leafs)}</div>' if leafs else ""
    return (f'<div class="lv d{depth}">'
            f'<div class="hd">{dot}{esc(head)}{v}{nt}</div>'
            f'{body}{inner}</div>')


def build(*, title: str, meta: str, sections: list) -> str:
    body = "\n  ".join(sections)
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <h1>{esc(title)}</h1>
  <div class="meta">{esc(meta)}</div>
  {body}
  <div class="footer">큐텐재팬 소싱 파이프라인 · 모든 시각 KST</div>
</div>
</body>
</html>"""


def section(no: int, name: str, inner: str) -> str:
    return f'<h2><span class="num">{no}</span> {esc(name)}</h2>\n  {inner}'


def check(html_text: str) -> list:
    """태그가 어긋나지 않았는지 확인한다. 깨진 리포트를 내보내지 않기 위함."""
    bad = []
    for tag in ("table", "tr", "div", "span"):
        o = html_text.count(f"<{tag}>") + html_text.count(f'<{tag} ')
        c = html_text.count(f"</{tag}>")
        if o != c:
            bad.append(f"{tag}: 열림 {o} / 닫힘 {c}")
    return bad
