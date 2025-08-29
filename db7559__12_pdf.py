import streamlit as st
import pandas as pd
import io
import requests
from PIL import Image
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.lib.utils import ImageReader
import time
from pathlib import Path
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
import re
import unicodedata as _ud

# =========================
# フォント設定（同梱前提）
#  Base : IPAexGothic.ttf（本文）
#  Fallback: NotoSansSymbols2-Regular.ttf（歯科記号 ⏊/⏉/⌝/⌟/⌜/⌞ ほか）
# =========================
SYM_FALLBACK_NAME = "SymFallback"

def _setup_font():
    here = Path(__file__).parent
    fonts_dir = here / "fonts"
    fonts_dir.mkdir(exist_ok=True)

    # 本文（日本語）
    ipa = fonts_dir / "IPAexGothic.ttf"
    if ipa.exists():
        pdfmetrics.registerFont(TTFont("BaseJP", str(ipa)))
        base_font_name = "BaseJP"
    else:
        pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
        base_font_name = "HeiseiKakuGo-W5"
        st.warning("⚠️ fonts/IPAexGothic.ttf が見つからないため HeiseiKakuGo-W5 にフォールバックします。")

    # 記号フォールバック
    sym_candidates = [
        fonts_dir / "NotoSansSymbols2-Regular.ttf",
        here / "NotoSansSymbols2-Regular.ttf",
        Path("/System/Library/Fonts/Supplemental/NotoSansSymbols2-Regular.ttf"),
        Path("C:/Windows/Fonts/NotoSansSymbols2-Regular.ttf"),
    ]
    for p in sym_candidates:
        if p.exists():
            pdfmetrics.registerFont(TTFont(SYM_FALLBACK_NAME, str(p)))
            break
    else:
        st.error("❌ 記号用フォントが見つかりません。`fonts/NotoSansSymbols2-Regular.ttf` を配置してください。")

    return base_font_name

JAPANESE_FONT = _setup_font()

# ========= 記号判定（ここでシンボル用フォントへ振る）=========
PALMER_SYMBOLS = set("⌜⌝⌞⌟⏌⏋⏊⏉⎿⏀′″ʼʹ﹅﹆")

def _needs_symbol_font(ch: str) -> bool:
    cp = ord(ch)
    if ch in PALMER_SYMBOLS:
        return True
    ranges = [
        (0x2500, 0x257F),  # Box Drawing
        (0x2580, 0x259F),  # Block Elements
        (0x25A0, 0x25FF),  # Geometric Shapes
        (0x2190, 0x21FF),  # Arrows
        (0x2300, 0x23FF),  # Misc Technical（⏊/⏉/⌝… を含む）
        (0x2200, 0x22FF),  # Math Operators
        (0x2070, 0x209F),  # Sup/Sub
        (0x02B0, 0x02FF),  # Modifier Letters
        (0x0300, 0x036F),  # Combining
        (0xFFE0, 0xFFEE),  # 全角記号（保険）
    ]
    for a, b in ranges:
        if a <= cp <= b:
            return True
    cat = _ud.category(ch)
    if cat in {"Sm", "So", "Sk"}:
        return True
    return False

def draw_with_fallback(c, x, y, text, base_font, size, sym_font=SYM_FALLBACK_NAME):
    """文字単位でベース/記号フォントを切替えて1行描画（置換はしない＝原文厳密出力）"""
    pen_x = x
    buf = ""
    cur_font = base_font
    registered = set(pdfmetrics.getRegisteredFontNames())

    def flush(seg, font_name):
        nonlocal pen_x
        if not seg:
            return
        c.setFont(font_name, size)
        c.drawString(pen_x, y, seg)
        pen_x += stringWidth(seg, font_name, size)

    for ch in (text or ""):
        use_sym = _needs_symbol_font(ch) and (sym_font in registered)
        target = sym_font if use_sym else base_font
        if target != cur_font:
            flush(buf, cur_font)
            buf = ch
            cur_font = target
        else:
            buf += ch
    flush(buf, cur_font)
    c.setFont(base_font, size)

# ====== （任意）代替表示トグル：フォントが無い環境だけ使う ======
st.sidebar.markdown("### ⚙️ PDFの歯式記号")
use_fallback = st.sidebar.checkbox("フォントが無い場合だけ代替記号で描く（┬/┴/┐/┘/┌/└）", value=False)

DENTAL_SAFE_FALLBACK = {
    # アーチ（両側）
    "\u23CA": "\u252C",  # ⏊ (UP+HORIZONTAL=上顎) -> ┬
    "\u23C9": "\u2534",  # ⏉ (DOWN+HORIZONTAL=下顎) -> ┴
    # 象限（片側）
    "\u231D": "\u2510",  # 右上 ⌝ -> ┐
    "\u231F": "\u2518",  # 右下 ⌟ -> ┘
    "\u231C": "\u250C",  # 左上 ⌜ -> ┌
    "\u231E": "\u2514",  # 左下 ⌞ -> └
}
def _maybe_fallback_for_pdf(s: str) -> str:
    if not use_fallback:
        return s  # 厳密モード：一切置換しない
    return "".join(DENTAL_SAFE_FALLBACK.get(ch, ch) for ch in (s or ""))

# =========================
# アプリ本体
# =========================
st.set_page_config(page_title="🔍 学生指導用データベース", layout="wide")
st.title("🔍 学生指導用データベース")

# フォント確認＆特殊文字診断
with st.expander("🧪 フォント登録確認 / 特殊文字診断", expanded=False):
    cols = st.columns(3)
    with cols[0]:
        if st.button("登録済みフォントを表示"):
            st.write(sorted(pdfmetrics.getRegisteredFontNames()))
    with cols[1]:
        st.caption("ヒット1件目から日本語・英数以外の文字を抽出して表示します")
        if st.button("特殊文字を抽出"):
            if "df_filtered" in st.session_state and len(st.session_state["df_filtered"]) > 0:
                txt = st.session_state["diagnostic_text"]
                specials = []
                for ch in txt:
                    if ch.isalnum() or ch in " 　、。・，．()（）[]【】{}｛｝:：;；!?！？+-/％%．,．":
                        continue
                    try:
                        name = _ud.name(ch)
                    except Exception:
                        name = "(no name)"
                    specials.append({"char": ch, "U+": f"U+{ord(ch):04X}", "name": name})
                st.write(specials if specials else "特殊文字は見つかりませんでした。")
            else:
                st.write("まず検索してヒットを出してください。")
    with cols[2]:
        st.caption("PDFに入る文字を確認（先頭120文字）")
        if st.button("PDFに流す文字を表示"):
            if "df_filtered" in st.session_state and len(st.session_state["df_filtered"]) > 0:
                raw = st.session_state["diagnostic_text"]
                prepared = _maybe_fallback_for_pdf(raw)
                st.write({"raw": raw[:120], "pdf_input": prepared[:120], "fallback_mode": use_fallback})
            else:
                st.write("まず検索してヒットを出してください。")

# ===== 列名正規化 & 安全取得 =====
def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    def _clean(s):
        s = str(s).replace("\ufeff", "")
        return re.sub(r"[\u3000 \t\r\n]+", "", s)
    df = df.copy()
    df.columns = [_clean(c) for c in df.columns]
    alias = {
        "問題文":  ["設問", "問題", "本文"],
        "選択肢1": ["選択肢Ａ","選択肢a","A","ａ"],
        "選択肢2": ["選択肢Ｂ","選択肢b","B","ｂ"],
        "選択肢3": ["選択肢Ｃ","選択肢c","C","ｃ"],
        "選択肢4": ["選択肢Ｄ","選択肢d","D","ｄ"],
        "選択肢5": ["選択肢Ｅ","選択肢e","E","ｅ"],
        "正解":    ["解答","答え","ans","answer"],
        "科目分類": ["分類","科目","カテゴリ","カテゴリー"],
        "リンクURL": ["画像URL","画像リンク","リンク","画像Link"],
    }
    colset = set(df.columns)
    for canon, cands in alias.items():
        if canon in colset: continue
        for c in cands:
            if c in colset:
                df.rename(columns={c: canon}, inplace=True)
                colset.add(canon)
                break
    return df

def safe_get(row: pd.Series | dict, keys, default=""):
    if isinstance(row, pd.Series):
        row = row.to_dict()
    for k in keys:
        if k in row:
            v = row.get(k)
            try:
                if pd.isna(v): continue
            except Exception:
                pass
            s = str(v).strip() if v is not None else ""
            if s: return s
    return default

def ensure_output_columns(df: pd.DataFrame) -> pd.DataFrame:
    need = ["問題文","選択肢1","選択肢2","選択肢3","選択肢4","選択肢5","正解","科目分類","リンクURL"]
    out = df.copy()
    for c in need:
        if c not in out.columns: out[c] = ""
    return out

# ===== データ読み込み =====
df = pd.read_csv("97_118DB.csv", dtype=str, encoding="utf-8-sig")
df = df.fillna("")
df = normalize_columns(df)

# ===== 検索 =====
query = st.text_input("問題文・選択肢・分類で検索:")
st.caption("💡 検索語を `&` でつなげるとAND検索（例: レジン & 硬さ）")
if not query:
    st.stop()

keywords = [kw.strip() for kw in query.split("&") if kw.strip()]

def row_text(r: pd.Series) -> str:
    parts = [
        safe_get(r, ["問題文","設問","問題","本文"]),
        *[safe_get(r, [f"選択肢{i}"]) for i in range(1,6)],
        safe_get(r, ["正解","解答","答え"]),
        safe_get(r, ["科目分類","分類","科目"]),
    ]
    return " ".join([p for p in parts if p])

df_filtered = df[df.apply(
    lambda row: all(kw.lower() in row_text(row).lower() for kw in keywords),
    axis=1
)]
df_filtered = df_filtered.reset_index(drop=True)
st.session_state["df_filtered"] = df_filtered
st.session_state["diagnostic_text"] = row_text(df_filtered.iloc[0]) if len(df_filtered) > 0 else ""

st.info(f"{len(df_filtered)}件ヒットしました")

timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
file_prefix = f"{(query if query else '検索なし')}{timestamp}"

# ===== CSV =====
csv_buffer = io.StringIO()
ensure_output_columns(df_filtered).to_csv(csv_buffer, index=False)
st.download_button("📥 ヒット結果をCSVダウンロード", csv_buffer.getvalue(), f"{file_prefix}.csv", "text/csv")

# ===== TXT =====
def convert_google_drive_link(url):
    if "drive.google.com" in url and "/file/d/" in url:
        try:
            file_id = url.split("/file/d/")[1].split("/")[0]
            return f"https://drive.google.com/uc?export=view&id={file_id}"
        except Exception:
            return url
    return url

def wrap_text(text: str, max_width: float, font_name: str, font_size: int):
    # ★厳密モード：置換しない。Fallbackモードのみ代替記号に（表示上の保険）
    s = _maybe_fallback_for_pdf("" if text is None else str(text))
    if s == "":
        return [""]
    lines, buf = [], ""
    for ch in s:
        if stringWidth(buf + ch, font_name, font_size) <= max_width:
            buf += ch
        else:
            lines.append(buf); buf = ch
    if buf: lines.append(buf)
    return lines

def wrapped_lines(prefix: str, value: str, usable_width: float, font: str, size: int):
    return wrap_text(f"{prefix}{value}", usable_width, font, size)

def format_record_to_text(row: pd.Series) -> str:
    q = safe_get(row, ["問題文","設問","問題","本文"])
    parts = [f"問題文: {q}"]
    for i in range(1, 6):
        c = safe_get(row, [f"選択肢{i}"])
        if c: parts.append(f"選択肢{i}: {c}")
    parts.append(f"正解: {safe_get(row, ['正解','解答','答え'])}")
    parts.append(f"分類: {safe_get(row, ['科目分類','分類','科目'])}")
    link = safe_get(row, ["リンクURL","画像URL","画像リンク","リンク","画像Link"])
    if link:
        parts.append(f"画像リンク: {convert_google_drive_link(link)}（PDFに画像表示）")
    return "\n".join(parts)

txt_buffer = io.StringIO()
for _, row in df_filtered.iterrows():
    txt_buffer.write(format_record_to_text(row))
    txt_buffer.write("\n\n" + "-"*40 + "\n\n")
st.download_button("📄 ヒット結果をTEXTダウンロード", txt_buffer.getvalue(), f"{file_prefix}.txt", "text/plain")

# ===== PDF =====
def create_pdf(records, progress=None, status=None, start_time=None):
    pdf_buffer = io.BytesIO()
    c = canvas.Canvas(pdf_buffer, pagesize=A4)
    c.setFont(JAPANESE_FONT, 12)
    width, height = A4

    top_margin, bottom_margin = 40, 60
    left_margin, right_margin = 40, 40
    usable_width = width - left_margin - right_margin
    page_usable_h = (height - top_margin) - bottom_margin
    line_h = 18
    y = height - top_margin

    total = len(records)
    if start_time is None: start_time = time.time()

    def fmt(sec):
        m = int(sec // 60); s = int(sec % 60)
        return f"{m:02d}:{s:02d}"

    def new_page():
        nonlocal y
        c.showPage()
        c.setFont(JAPANESE_FONT, 12)
        y = height - top_margin

    def draw_wrapped_lines(lines):
        nonlocal y
        for ln in lines:
            draw_with_fallback(c, left_margin, y, ln, JAPANESE_FONT, 12)
            y -= line_h

    for idx, (_, row) in enumerate(records.iterrows(), start=1):
        q = safe_get(row, ["問題文","設問","問題","本文"])

        # 選択肢
        choices = []
        for i in range(1, 6):
            v = safe_get(row, [f"選択肢{i}"])
            if v: choices.append((i, v))

        ans = safe_get(row, ["正解","解答","答え"])
        cat = safe_get(row, ["科目分類","分類","科目"])

        # 画像の事前取得
        pil = None; img_est_h = 0
        link_raw = safe_get(row, ["リンクURL","画像URL","画像リンク","リンク"])
        if link_raw:
            try:
                image_url = convert_google_drive_link(link_raw)
                resp = requests.get(image_url, timeout=5)
                pil = Image.open(io.BytesIO(resp.content)).convert("RGB")
                iw, ih = pil.size
                scale = min(usable_width / iw, page_usable_h / ih, 1.0)
                nw, nh = iw * scale, ih * scale
                img_est_h = nh + 20
            except Exception:
                pil = None
                img_est_h = len(wrapped_lines("", "[画像読み込み失敗]", usable_width, JAPANESE_FONT, 12)) * line_h

        # 高さ見積り
        est_h = 0
        q_lines = wrapped_lines("問題文: ", q, usable_width, JAPANESE_FONT, 12)
        est_h += len(q_lines) * line_h
        choice_lines_list = []
        for i, v in choices:
            ls = wrapped_lines(f"選択肢{i}: ", v, usable_width, JAPANESE_FONT, 12)
            choice_lines_list.append(ls); est_h += len(ls) * line_h
        est_h += img_est_h if img_est_h else 0
        ans_lines = wrapped_lines("正解: ", ans, usable_width, JAPANESE_FONT, 12)
        cat_lines = wrapped_lines("分類: ", cat, usable_width, JAPANESE_FONT, 12)
        est_h += (len(ans_lines) + len(cat_lines)) * line_h + 20

        # ページ先頭は必ず問題文から
        if y - est_h < bottom_margin: new_page()

        # 描画
        draw_wrapped_lines(q_lines)
        for ls in choice_lines_list: draw_wrapped_lines(ls)

        if pil is not None:
            try:
                iw, ih = pil.size
                scale = min(usable_width / iw, page_usable_h / ih, 1.0)
                nw, nh = iw * scale, ih * scale
                if y - nh < bottom_margin: new_page()
                remaining = y - bottom_margin
                if nh > remaining:
                    adj = remaining / nh
                    nw, nh = nw * adj, nh * adj
                img_io = io.BytesIO(); pil.save(img_io, format="PNG"); img_io.seek(0)
                img_reader = ImageReader(img_io)
                c.drawImage(img_reader, left_margin, y - nh, width=nw, height=nh,
                            preserveAspectRatio=True, mask='auto')
                y -= nh + 20
            except Exception as e:
                err_lines = wrapped_lines("", f"[画像読み込み失敗: {e}]", usable_width, JAPANESE_FONT, 12)
                draw_wrapped_lines(err_lines)
        else:
            if link_raw:
                draw_wrapped_lines(wrapped_lines("", "[画像読み込み失敗]", usable_width, JAPANESE_FONT, 12))

        draw_wrapped_lines(ans_lines)
        draw_wrapped_lines(cat_lines)

        if y - 20 < bottom_margin: new_page()
        else: y -= 20

        # 進捗＆ETA
        if st.session_state.get("progress_on"):
            st.session_state["progress"].progress(min(idx / max(total, 1), 1.0))
            elapsed = time.time() - start_time
            avg_per_item = elapsed / idx if idx > 0 else 0
            remaining = max(total - idx, 0) * avg_per_item
            if "eta_placeholder" in st.session_state:
                st.session_state["eta_placeholder"].markdown(
                    f"⏳ 残り目安: **{int(remaining//60):02d}:{int(remaining%60):02d}**"
                    f"（経過 {int(elapsed//60):02d}:{int(elapsed%60):02d} / {idx}/{total} 件）"
                )

    c.save()
    pdf_buffer.seek(0)
    return pdf_buffer.getvalue()

# ===== PDF 生成 =====
if "pdf_bytes" not in st.session_state:
    st.session_state["pdf_bytes"] = None

if st.button("🖨️ PDFを作成（画像付き）"):
    st.session_state["progress_on"] = True
    st.session_state["progress"] = st.progress(0.0)
    st.session_state["eta_placeholder"] = st.empty()

    start = time.time()
    with st.spinner("PDFを作成中…"):
        st.session_state["pdf_bytes"] = create_pdf(df_filtered, start_time=start)
    st.session_state["progress_on"] = False

    total_sec = time.time() - start
    st.session_state["eta_placeholder"].markdown(
        f"✅ 完了：合計 **{int(total_sec//60):02d}:{int(total_sec%60):02d}**"
    )
    st.success("✅ PDF作成完了！")

if st.session_state["pdf_bytes"] is not None:
    st.download_button(
        "📄 ヒット結果をPDFダウンロード",
        st.session_state["pdf_bytes"],
        f"{file_prefix}.pdf",
        "application/pdf"
    )

# ===== 一覧 =====
st.markdown("### 🔍 ヒットした問題一覧")
for i, (_, record) in enumerate(df_filtered.iterrows()):
    title = safe_get(record, ["問題文","設問","問題","本文"])
    with st.expander(f"{i+1}. {title[:50]}..."):
        st.markdown("### 📝 問題文")
        st.write(title)

        st.markdown("### ✏️ 選択肢")
        for j in range(1, 6):
            val = safe_get(record, [f"選択肢{j}"])
            if val: st.write(f"- {val}")

        show_ans = st.checkbox("正解を表示する", key=f"show_answer_{i}", value=False)
        if show_ans:
            st.markdown(f"**✅ 正解:** {safe_get(record, ['正解','解答','答え'])}")
        else:
            st.markdown("**✅ 正解:** |||（クリックで表示）|||")

        st.markdown(f"**📚 分類:** {safe_get(record, ['科目分類','分類','科目'])}")

        link = safe_get(record, ["リンクURL","画像URL","画像リンク","リンク"])
        if link:
            st.markdown(f"[画像リンクはこちら]({convert_google_drive_link(link)})")
        else:
            st.write("（画像リンクはありません）")
