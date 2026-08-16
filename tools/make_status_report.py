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

  /* ── 트리맵: 면적이 건수에 비례한다 ─────────────────────
     주식 히트맵과 같은 방식(사장님 요청 2026-08-17).
     - 넓이로 규모를 본다. 숫자를 안 읽어도 뭐가 많은지 보인다.
     - 색으로 상태를 본다. 초록은 살아남고 회색은 버려진다.
     - 중첩으로 상하관계를 본다. 큰 칸 안에 작은 칸이 들어간다.

     정확한 squarified 알고리즘 대신 flex 비율로 나눈다. 방향을
     번갈아(가로→세로→가로) 쪼개면 칸 모양이 지나치게 길쭉해지지
     않는다. */
  .tmap{display:flex; width:100%; gap:3px; border-radius:8px;
    overflow:hidden; background:#0b0d12; padding:3px;}
  .tm{position:relative; display:flex; gap:3px; min-width:0; min-height:0;
    border-radius:4px; overflow:hidden;}
  .tm.row{flex-direction:row;} .tm.col{flex-direction:column;}
  .tm > .cap{position:absolute; left:0; top:0; right:0; z-index:2;
    font-size:9.5px; font-weight:700; letter-spacing:.02em;
    padding:2px 5px; color:rgba(255,255,255,.92);
    background:rgba(0,0,0,.34); text-transform:none; white-space:nowrap;
    overflow:hidden; text-overflow:ellipsis;}
  .tm.hascap{padding-top:15px;}
  /* 잎 칸 — 이름과 숫자를 가운데 */
  .cell{display:flex; flex-direction:column; align-items:center;
    justify-content:center; min-width:0; min-height:0; border-radius:4px;
    padding:4px; text-align:center; overflow:hidden; line-height:1.2;}
  .cell .nm{font-size:11px; font-weight:700; color:#fff;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
    max-width:100%;}
  .cell .qt{font-size:15px; font-weight:800; color:#fff; margin-top:1px;}
  .cell .sm .qt{font-size:12px;}
  .cell.tiny .nm{font-size:9px;} .cell.tiny .qt{font-size:11px;}
  /* 상태 색 — 히트맵처럼 진하게 */
  .cell.go{background:#1f9d63;}
  .cell.todo{background:#c8901a;}
  .cell.wait{background:#2f6fb5;}
  .cell.drop{background:#3a3f4a;}
  .cell.drop .nm{color:#8a919d; font-size:9.5px;}
  .cell.drop .qt{color:#a9b0bb; font-size:12px;}
  /* 버려지는 것을 담는 얇은 띠 — 면적 경쟁에서 빼고 아래에 붙인다 */
  .dropbar{display:flex; gap:3px; margin-top:4px;}
  .dropbar .cell{padding:5px 8px; border-radius:4px; flex-direction:row;
    gap:6px; align-items:baseline; justify-content:flex-start;}
  .dropbar .cell .nm{font-size:10px;} .dropbar .cell .qt{font-size:12.5px;}
  .cell.bad{background:#c0392b;}
  .tm.grp{background:rgba(255,255,255,.05);}

  /* ── 표 안의 표 ─────────────────────────────────────────
     사장님 요청 2026-08-17: "수확본 아래 통합본 아래 검증대상이
     들어가게 표인표로" → "표안에 표로 보이게" → "하위인게 확실히
     티가 나게".

     세 번 고쳤다. 마지막 요구가 핵심이다 — **하위임이 티가 나야 한다.**
     그래서 네 가지를 동시에 쓴다:
       1) 안쪽 표를 담는 칸(.holder)에 왼쪽 굵은 띠 + 넉넉한 여백
       2) 머리글에 "└ 안에 들어있음" 화살표를 찍는다
       3) 깊이마다 왼쪽 들여쓰기가 누적된다
       4) 안으로 갈수록 머리 색이 밝아진다 */
  .nt{width:100%; border-collapse:collapse; margin:0;}
  .nt th, .nt td{border:1px solid #4a5262; padding:0;}
  .nt > tbody > tr > th{background:#2b3242; color:#fff; text-align:left;
    font-size:12.5px; font-weight:800; padding:9px 11px;}
  .nt > tbody > tr > th .q{float:right; font-size:14.5px;}
  .nt > tbody > tr > th .u{font-size:10px; font-weight:500; opacity:.7;
    margin-left:4px;}
  .nt > tbody > tr > th .in{font-size:10.5px; font-weight:600;
    opacity:.72; margin-right:5px;}

  .nt td.leafcell{padding:0;}
  .nt table.rowsT{width:100%; border-collapse:collapse;}
  .nt table.rowsT td{border:none; border-bottom:1px solid #3b4252;
    padding:6px 11px; font-size:11.5px;}
  .nt table.rowsT tr:last-child td{border-bottom:none;}
  .nt table.rowsT td.q{text-align:right; font-size:13.5px; font-weight:800;
    white-space:nowrap; width:1%;}
  .nt table.rowsT td.a{text-align:right; font-size:10px; opacity:.85;
    white-space:nowrap; width:1%; padding-left:6px;}
  tr.go td{background:#1f9d63; color:#fff;}
  tr.todo td{background:#c8901a; color:#fff;}
  tr.wait td{background:#2f6fb5; color:#fff;}
  tr.drop td{background:#31363f; color:#98a0ac;}
  tr.plain td{background:rgba(255,255,255,.05); color:#cfd6e4;}

  /* ★ 하위임을 드러내는 칸 — 왼쪽 굵은 띠 + 들여쓰기 */
  .nt td.holder{padding:12px 12px 12px 26px; background:rgba(0,0,0,.3);
    border-left:6px solid #6b7a9e; position:relative;}
  .nt td.holder::before{content:"└"; position:absolute; left:9px; top:10px;
    color:#8fa0c4; font-size:14px; font-weight:800; line-height:1;}
  .nt td.holder::after{content:"안에 들어있는 것"; position:absolute;
    left:26px; top:-1px; font-size:8.5px; color:#7d8ba8; letter-spacing:.04em;}

  /* 깊이별 머리 색과 왼쪽 띠 색 */
  .k1 > tbody > tr > th{background:#2b3242;}
  .k2 > tbody > tr > th{background:#3c4866;}
  .k3 > tbody > tr > th{background:#4d5c8a;}
  .k4 > tbody > tr > th{background:#6070ab;}
  /* 형제를 나란히 놓을 때 */
  .sib{display:flex; flex-direction:column; gap:8px;}
  .sib > .sibnote{font-size:10px; color:#7d8ba8; letter-spacing:.03em;}
  .k1 td.holder{border-left-color:#3c4866;}
  .k2 td.holder{border-left-color:#4d5c8a;}
  .k3 td.holder{border-left-color:#6070ab;}

  /* ── 상자 지도 ─────────────────────────────────────────
     형제는 가로로, 자식은 부모 안에(사장님 그림 2026-08-17).

     [고친 것 — 실측] 처음엔 상자 너비를 건수에 그대로 비례시켰더니
     좁은 상자에서 글씨가 한 글자씩 세로로 늘어졌다. 단위("건")도
     flex 틈에 끼어 커다란 빈 상자로 보였다.
       · 최소 너비를 주고, 넘치면 줄바꿈(wrap)한다
       · 제목은 한 줄로 고정(nowrap), 넘치면 말줄임
       · 숫자와 단위는 한 덩어리로 묶는다 */
  .bmap{border-radius:10px; padding:12px; min-width:0;}
  .bmap .ttl{display:flex; align-items:baseline; gap:6px; margin-bottom:9px;
    white-space:nowrap; overflow:hidden;}
  .bmap .ttl .nmx{font-size:12px; font-weight:700; color:#fff;
    overflow:hidden; text-overflow:ellipsis; min-width:0; letter-spacing:-.01em;}
  .bmap .ttl .qx{font-size:15px; font-weight:800; color:#fff;
    margin-left:auto; white-space:nowrap;}
  .bmap .ttl .qx em{font-style:normal; font-size:9.5px; font-weight:500;
    opacity:.7; margin-left:2px;}
  .bmap .kids{display:flex; gap:5px; align-items:stretch; flex-wrap:wrap;}
  .bmap .kids > .bmap{flex:1 1 130px; min-width:130px;}
  .bmap .note{font-size:10px; color:rgba(255,255,255,.72); margin-top:7px;
    line-height:1.45;}

  /* 색 — 남색 바탕에 채도 낮은 포인트 */
  .b0{background:#161b26; border:1px solid #2c3444;}
  .b1{background:#1e2635; border:1px solid #364258;}
  .b2{background:#243046; border:1px solid #3d4d6b;}
  .b3{background:#2a3852; border:1px solid #46587b;}
  .bg{background:#1e7a5a; border:1px solid #2fa87c;}   /* 된 것 */
  .bt{background:#a8761f; border:1px solid #d09a35;}   /* 할 것 */
  .bw{background:#2a5b8f; border:1px solid #3f7cbd;}   /* 아직 */
  .bx{background:#333a47; border:1px solid #454e5f;}   /* 버림 */
  .bx .ttl .nmx, .bx .ttl .qx{color:#a8b0bd;}
  .bx .note{color:#7f8798;}

  /* 상자 사이 화살표 — 방향만 보여준다.
     [사장님 요청 2026-08-17] "글을 쓰지 말고 화살표만 겹치게".
     라벨을 달면 읽어야 해서 오히려 흐름이 안 보인다. 폭 0으로 두고
     상자 사이 틈에 겹쳐 놓아 상자 크기에 영향을 주지 않는다. */
  .bmap .kids{position:relative;}
  .arw{flex:0 0 0; width:0; align-self:center; position:relative;
    z-index:5; pointer-events:none;}
  /* 화살표를 상자 위에 올려 놓는다. 원판을 깔고 그 안에 삼각형을
     넣어, 상자 색 위에서도 또렷하게 보이게 한다. */
  .arw::before{content:"▶"; position:absolute; left:-13px; top:-13px;
    width:26px; height:26px; border-radius:50%;
    background:#0d1117; border:2px solid #8fa0bb; color:#dbe4f0;
    font-size:12px; display:flex; align-items:center;
    justify-content:center; padding-left:2px;
    box-shadow:0 2px 8px rgba(0,0,0,.55);}

  .bmap .lines{display:flex; flex-direction:column; gap:3px; margin-top:7px;}
  .bline{display:flex; align-items:center; gap:7px; border-radius:5px;
    padding:5px 8px; font-size:10.5px; background:rgba(0,0,0,.24); color:#fff;
    white-space:nowrap;}
  .bline .nm{flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis;}
  .bline .q{font-weight:800; font-size:12px;}
  .bline .ar{font-size:9.5px; opacity:.8;}

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



def cell(name: str, qty: int, tone: str = "drop", note: str = "",
         size: str = "") -> dict:
    """트리맵의 한 칸. 넓이는 qty에 비례한다."""
    return {"kind": "cell", "name": name, "qty": qty, "tone": tone,
            "note": note, "size": size}


def group(caption: str, children: list) -> dict:
    """트리맵의 묶음. 자식들의 합만큼 넓이를 차지한다."""
    return {"kind": "group", "caption": caption, "children": children}


def _tm_qty(n: dict) -> int:
    if n["kind"] == "cell":
        return max(n["qty"], 0)
    return sum(_tm_qty(c) for c in n["children"])


def _tm_render(nodes: list, horizontal: bool) -> str:
    total = sum(_tm_qty(n) for n in nodes) or 1
    out = []
    for n in nodes:
        q = _tm_qty(n)
        grow = max(q / total * 100, 1.2)   # 너무 얇아 안 보이는 칸 방지
        style = f"flex:{grow:.3f} 1 0;"
        if n["kind"] == "cell":
            tiny = " tiny" if q / total < 0.035 else ""
            nt = (f'<div class="nm" style="opacity:.75;font-size:9px;'
                  f'font-weight:500">{esc(n["note"])}</div>' if n["note"] else "")
            out.append(f'<div class="cell {n["tone"]}{tiny}" style="{style}">'
                       f'<div class="nm">{esc(n["name"])}</div>'
                       f'<div class="qt">{num(n["qty"])}</div>{nt}</div>')
        else:
            cap = (f'<div class="cap">{esc(n["caption"])} '
                   f'{num(_tm_qty(n))}</div>') if n["caption"] else ""
            cls = "col" if horizontal else "row"
            hc = " hascap" if n["caption"] else ""
            inner = _tm_render(n["children"], not horizontal)
            out.append(f'<div class="tm grp {cls}{hc}" style="{style}">'
                       f'{cap}{inner}</div>')
    return "".join(out)


def treemap(nodes: list, height: int = 330) -> str:
    """면적이 건수에 비례하는 지도.

    [왜 — 사장님 요청 2026-08-17] 주식 히트맵처럼 그려 달라.
    숫자를 읽지 않아도 무엇이 많고 적은지, 무엇이 살아남고 버려지는지
    한눈에 보인다.
    """
    return (f'<div class="tmap row" style="height:{height}px;">'
            f'{_tm_render(nodes, True)}</div>')



def nrow(name: str, qty, tone: str = "plain", arrow: str = "") -> str:
    """표 안의 한 행. 이름 | 숫자 | 화살표 세 칸."""
    ar = f'<td class="a">{esc(arrow)}</td>' if arrow else '<td class="a"></td>'
    return (f'<tr class="{tone}"><td class="n">{esc(name)}</td>'
            f'<td class="q">{num(qty)}</td>{ar}</tr>')


def ntable(depth: int, title: str, qty, unit: str = "",
           rows: list = None, inner: str = "") -> str:
    """표 안의 표 한 겹.

    바깥 표의 칸 하나가 통째로 안쪽 표를 품는다. 격자 선을 그려
    실제 표로 보이게 하고, 안쪽 표 둘레에 여백을 둬서 '들어있음'이
    눈으로 읽히게 한다.
    """
    u = f'<span class="u">{esc(unit)}</span>' if unit else ""
    # 2층부터는 머리글에 "◂ 위 표 안" 표시를 붙여 하위임을 못 박는다
    mark = f'<span class="in">{"▸" * (depth - 1)} {depth}층</span>' if depth > 1 else ""
    body = (f'<tr><td class="leafcell"><table class="rowsT"><tbody>'
            f'{"".join(rows)}</tbody></table></td></tr>') if rows else ""
    # inner에 표가 여러 개 오면 형제로 나란히 놓는다.
    # [사장님 지적 2026-08-17] "창고 = 안 옮긴 것 + 통합본이면
    # 수평하게 있어야지" — 형제인데 부모-자식으로 그렸었다.
    kid = f'<tr><td class="holder">{inner}</td></tr>' if inner else ""
    return (f'<table class="nt k{depth}"><tbody>'
            f'<tr><th>{mark}{esc(title)}'
            f'<span class="q">{num(qty)}{u}</span></th></tr>'
            f'{body}{kid}</tbody></table>')




def arrow(label: str = "") -> str:  # noqa: ARG001
    """상자 사이 틈에 겹쳐 놓는 화살표. 방향만 보여준다.

    [사장님 요청 2026-08-17] 라벨은 달지 않는다 — 읽어야 하는 글이
    붙으면 오히려 흐름이 안 보인다. 폭 0으로 두고 겹쳐 놓아 상자
    크기에도 영향을 주지 않는다.
    """
    return '<div class="arw"></div>' 


def bline(name: str, qty, arrow: str = "") -> str:
    """상자 안의 한 줄(자식 상자를 만들 만큼 크지 않은 항목)."""
    ar = f'<span class="ar">{esc(arrow)}</span>' if arrow else ""
    return (f'<div class="bline"><span class="nm">{esc(name)}</span>'
            f'<span class="q">{num(qty)}</span>{ar}</div>')


def bbox(cls: str, title: str, qty=None, unit: str = "",
         kids: list = None, lines: list = None, note: str = "",
         grow: float = None) -> str:
    """상자 하나. 자식(kids)은 **가로로 나란히** 놓인다.

    [사장님이 그림으로 지정한 방식 2026-08-17]
    형제는 가로, 자식은 부모 안에. 세로로 쌓으면 같은 층인지
    아래 층인지 헷갈린다.

    grow: 가로 폭 비율. 건수에 비례시키고 싶을 때 넘긴다.
    """
    u = f'<em>{esc(unit)}</em>' if unit else ""
    q = f'<span class="qx">{num(qty)}{u}</span>' if qty is not None else ""
    body = (f'<div class="kids">{"".join(kids)}</div>' if kids else "")
    ln = (f'<div class="lines">{"".join(lines)}</div>' if lines else "")
    nt = f'<div class="note">{note}</div>' if note else ""
    # 너비 비례는 쓰되 최소 폭을 지켜 글씨가 세로로 늘어지지 않게 한다
    style = f' style="flex:{grow} 1 130px;"' if grow is not None else ""
    return (f'<div class="bmap {cls}"{style}>'
            f'<div class="ttl"><span class="nmx">{esc(title)}</span>{q}</div>'
            f'{body}{ln}{nt}</div>')


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
