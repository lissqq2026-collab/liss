"""ui/plotly_autoscale.py — 同花顺式 Y 轴自适应。

Plotly 默认在 X 缩放/平移时不会重算 Y 轴，导致放大后 K 线被压扁、看不出陡峭度。
本模块注入一段 JS：监听每张 K 线图的 plotly_relayout，当 X 范围变化时，
把可见窗口内蜡烛的 high/low 取出，重设 yaxis.range —— 蜡烛始终撑满主图，
任何缩放级别都保持陡峭，与同花顺一致。

实现要点（踩坑记录）：
  - X 范围以 relayout 事件里的 `xaxis.range[0]/[1]`（日期字符串）为准，
    再用 `new Date()` 与蜡烛 x 统一换算成毫秒比较；不要读 _fullLayout.xaxis.range，
    其单位在 date 轴上不确定，会导致过滤后蜡烛全被剔除 → Y 永不更新。
"""
import streamlit.components.v1 as components


def inject_y_autoscale() -> None:
    """在页面末尾调用一次：为当前页所有 K 线图装上 Y 轴随可见窗口自适应。"""
    components.html(
        """
        <script>
        (function(){
            var win = window.parent;
            var doc = win.document;

            function getPlots(){
                var out = [];
                try {
                    doc.querySelectorAll('.js-plotly-plot').forEach(function(el){ out.push(el); });
                } catch(e) {}
                var ifr = doc.querySelectorAll('iframe');
                for (var i = 0; i < ifr.length; i++) {
                    try {
                        var d = ifr[i].contentDocument || ifr[i].contentWindow.document;
                        if (!d) continue;
                        d.querySelectorAll('.js-plotly-plot').forEach(function(el){ out.push(el); });
                    } catch(e) {}
                }
                return out;
            }

            function findCandle(gd){
                if (!gd || !gd.data) return null;
                for (var i = 0; i < gd.data.length; i++) {
                    if (gd.data[i].type === 'candlestick') return gd.data[i];
                }
                return null;
            }

            function plotlyFor(gd){
                var w = gd.ownerDocument && gd.ownerDocument.defaultView;
                if (w && w.Plotly) return w.Plotly;
                return win.Plotly || window.Plotly;
            }

            function ms(v){
                if (v == null) return NaN;
                var t = (typeof v === 'number') ? v : (+new Date(v));
                return t;
            }

            // lo/hi 为日期字符串或数字；传 null 表示全量
            function rescale(gd, lo, hi){
                var c = findCandle(gd);
                if (!c || !c.x || !c.high || !c.low) return;
                var P = plotlyFor(gd);
                if (!P) return;
                var loMs = (lo == null) ? null : ms(lo);
                var hiMs = (hi == null) ? null : ms(hi);
                var pmin = Infinity, pmax = -Infinity;
                for (var i = 0; i < c.x.length; i++) {
                    if (loMs != null && hiMs != null) {
                        var t = ms(c.x[i]);
                        if (isNaN(t) || t < loMs || t > hiMs) continue;
                    }
                    var h = c.high[i], l = c.low[i];
                    if (h > pmax) pmax = h;
                    if (l < pmin) pmin = l;
                }
                if (!isFinite(pmin) || !isFinite(pmax) || pmax <= pmin) return;
                var pad = (pmax - pmin) * 0.04 || pmax * 0.01;
                gd.__yAutoBusy = true;
                P.relayout(gd, {'yaxis.range': [pmin - pad, pmax + pad], 'yaxis.autorange': false})
                 .then(function(){ gd.__yAutoBusy = false; })
                 .catch(function(){ gd.__yAutoBusy = false; });
            }

            function curRange(gd){
                // 优先取用户层 layout（zoom 后会被写成日期字符串）
                try {
                    var r = gd.layout && gd.layout.xaxis && gd.layout.xaxis.range;
                    if (r && r.length === 2) return [r[0], r[1]];
                } catch(e) {}
                return [null, null];
            }

            function attach(gd){
                if (gd.__yAutoAttached) return;
                if (!findCandle(gd)) return;
                if (typeof gd.on !== 'function') return;
                gd.__yAutoAttached = true;
                gd.on('plotly_relayout', function(ev){
                    if (gd.__yAutoBusy) return;
                    // 双击复位：全量重算
                    if (ev['xaxis.autorange'] === true) { rescale(gd, null, null); return; }
                    var lo, hi;
                    if (ev['xaxis.range[0]'] !== undefined) {
                        lo = ev['xaxis.range[0]']; hi = ev['xaxis.range[1]'];
                    } else if (Array.isArray(ev['xaxis.range'])) {
                        lo = ev['xaxis.range'][0]; hi = ev['xaxis.range'][1];
                    } else {
                        return;  // 与 X 范围无关的 relayout（如 yaxis.range）忽略
                    }
                    rescale(gd, lo, hi);
                });
                // 初次按当前 X 范围拟合一次
                var r0 = curRange(gd);
                rescale(gd, r0[0], r0[1]);
            }

            function scan(){ getPlots().forEach(attach); }

            scan();
            setTimeout(scan, 300);
            setTimeout(scan, 1000);
            try {
                var obs = new MutationObserver(function(){ scan(); });
                obs.observe(doc.body, { childList: true, subtree: true });
                setTimeout(function(){ obs.disconnect(); }, 5000);
            } catch(e) {}
        })();
        </script>
        """,
        height=0,
    )
